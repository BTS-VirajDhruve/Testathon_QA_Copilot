"""In-memory / JSON-persisted graph store with Neo4j-compatible interface."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.mongo import (
    get_qa_analyses_collection_sync,
    get_qa_bugs_collection_sync,
    get_qa_document_chunks_collection_sync,
    get_qa_documents_collection_sync,
    get_qa_edges_collection_sync,
    get_qa_external_knowledge_sources_collection_sync,
    get_qa_graph_versions_collection_sync,
    get_qa_nodes_collection_sync,
    get_qa_projects_collection_sync,
    get_qa_test_cases_collection_sync,
    get_qa_test_review_overrides_collection_sync,
    get_qa_test_reviews_collection_sync,
)
from app.models.enums import NodeType, Priority, RelationshipType, SourceType
from app.models.schemas import (
    GraphEdge,
    GraphNode,
    GraphPath,
    Provenance,
    SystemFlowGraph,
    new_id,
    utc_now,
)

logger = get_logger(__name__)


class GraphStoreProtocol(Protocol):
    def upsert_node(self, node: GraphNode) -> GraphNode: ...
    def upsert_edge(self, edge: GraphEdge) -> GraphEdge: ...
    def get_node(self, node_id: str) -> GraphNode | None: ...
    def get_project_graph(self, project_id: str) -> SystemFlowGraph: ...
    def save_project_graph(self, graph: SystemFlowGraph) -> SystemFlowGraph: ...
    def find_nodes(
        self,
        project_id: str,
        *,
        name: str | None = None,
        node_type: NodeType | None = None,
    ) -> list[GraphNode]: ...
    def neighbors(
        self,
        node_id: str,
        *,
        direction: str = "outgoing",
        relationship: str | None = None,
    ) -> list[tuple[GraphEdge, GraphNode]]: ...
    def discover_paths(
        self,
        project_id: str,
        root_id: str,
        *,
        max_depth: int = 8,
    ) -> list[GraphPath]: ...
    def impact_subgraph(
        self, node_id: str, *, max_depth: int = 4
    ) -> dict[str, Any]: ...


class InMemoryGraphStore:
    """Persistent JSON graph store — primary implementation for hackathon demo."""

    def __init__(self, path: str | None = None) -> None:
        settings = get_settings()
        self.path = Path(path or (Path(settings.data_dir) / "graph_store.json"))
        self._lock = threading.RLock()
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[str, GraphEdge] = {}
        self.projects: dict[str, dict[str, Any]] = {}
        self.documents: dict[str, dict[str, Any]] = {}
        self.test_cases: dict[str, dict[str, Any]] = {}
        self.bugs: dict[str, dict[str, Any]] = {}
        self.graph_versions: dict[str, list[dict[str, Any]]] = {}
        # project_id -> last Copilot analysis payload (JSON-serializable)
        self.latest_analyses: dict[str, dict[str, Any]] = {}
        # project_id::test_case_id -> persisted validity/automation review record
        self.test_reviews: dict[str, dict[str, Any]] = {}
        # project_id::test_case_id -> human automation-review override
        self.test_review_overrides: dict[str, dict[str, Any]] = {}
        # source_id -> ExternalKnowledgeSource (Atlassian imports)
        self.external_knowledge_sources: dict[str, dict[str, Any]] = {}
        self._load()

    @staticmethod
    def artifact_key(project_id: str, artifact_id: str) -> str:
        """Namespace artifact dict keys so TC-001 in project A cannot overwrite project B."""
        if "::" in artifact_id and artifact_id.startswith(f"{project_id}::"):
            return artifact_id
        return f"{project_id}::{artifact_id}"

    def upsert_test_case(self, project_id: str, case: dict[str, Any]) -> dict[str, Any]:
        payload = {**case, "project_id": project_id}
        tid = str(payload.get("test_case_id") or "")
        if not tid:
            tid = new_id("TC")
            payload["test_case_id"] = tid
        key = self.artifact_key(project_id, tid)
        with self._lock:
            self.test_cases[key] = payload
            self.persist()
        return payload

    def get_test_case(
        self, project_id: str, test_case_id: str
    ) -> dict[str, Any] | None:
        key = self.artifact_key(project_id, test_case_id)
        with self._lock:
            row = self.test_cases.get(key)
            if row and row.get("project_id") == project_id:
                return row
        return None

    def delete_test_case(self, project_id: str, test_case_id: str) -> bool:
        key = self.artifact_key(project_id, test_case_id)
        with self._lock:
            removed = key in self.test_cases and self.test_cases[key].get(
                "project_id"
            ) == project_id
            if removed:
                del self.test_cases[key]
            if removed:
                self.persist()
            return removed

    def update_project_meta(
        self, project_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self._lock:
            project = self.projects.get(project_id)
            if not project:
                return None
            project = {**project, **patch}
            self.projects[project_id] = project
            self.persist()
            return project

    def upsert_bug(self, project_id: str, bug: dict[str, Any]) -> dict[str, Any]:
        payload = {**bug, "project_id": project_id}
        bid = str(payload.get("bug_id") or "")
        if not bid:
            bid = new_id("BUG")
            payload["bug_id"] = bid
        key = self.artifact_key(project_id, bid)
        with self._lock:
            self.bugs[key] = payload
            self.persist()
        return payload

    def set_latest_analysis(self, project_id: str, analysis: dict[str, Any]) -> None:
        with self._lock:
            self.latest_analyses[project_id] = {**analysis, "project_id": project_id}
            self.persist()

    def get_latest_analysis(self, project_id: str) -> dict[str, Any] | None:
        return self.latest_analyses.get(project_id)

    def get_test_review(
        self, project_id: str, test_case_id: str
    ) -> dict[str, Any] | None:
        return self.test_reviews.get(self.artifact_key(project_id, test_case_id))

    def list_test_reviews(self, project_id: str) -> dict[str, dict[str, Any]]:
        prefix = f"{project_id}::"
        out: dict[str, dict[str, Any]] = {}
        for key, value in self.test_reviews.items():
            if key.startswith(prefix):
                out[key[len(prefix) :]] = value
        return out

    def set_test_review(
        self, project_id: str, test_case_id: str, review: dict[str, Any]
    ) -> dict[str, Any]:
        key = self.artifact_key(project_id, test_case_id)
        payload = {**review, "project_id": project_id, "test_case_id": test_case_id}
        with self._lock:
            self.test_reviews[key] = payload
            self.persist()
        return payload

    def bulk_set_test_reviews(
        self, project_id: str, reviews: list[dict[str, Any]]
    ) -> None:
        with self._lock:
            for review in reviews:
                test_case_id = str(review.get("test_case_id") or "")
                if not test_case_id:
                    continue
                key = self.artifact_key(project_id, test_case_id)
                self.test_reviews[key] = {
                    **review,
                    "project_id": project_id,
                    "test_case_id": test_case_id,
                }
            self.persist()

    def get_automation_capability_profile(
        self, project_id: str
    ) -> dict[str, Any] | None:
        project = self.projects.get(project_id)
        if not project:
            return None
        profile = project.get("automation_capability_profile")
        return profile if isinstance(profile, dict) else None

    def set_automation_capability_profile(
        self, project_id: str, profile: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            project = self.projects.get(project_id)
            if not project:
                raise KeyError(project_id)
            project["automation_capability_profile"] = profile
            self.projects[project_id] = project
            self.persist()
            return profile

    def get_test_review_override(
        self, project_id: str, test_case_id: str
    ) -> dict[str, Any] | None:
        key = self.artifact_key(project_id, test_case_id)
        return self.test_review_overrides.get(key)

    def list_test_review_overrides(self, project_id: str) -> dict[str, dict[str, Any]]:
        prefix = f"{project_id}::"
        out: dict[str, dict[str, Any]] = {}
        for key, value in self.test_review_overrides.items():
            if key.startswith(prefix):
                tid = key[len(prefix) :]
                out[tid] = value
        return out

    def set_test_review_override(
        self, project_id: str, test_case_id: str, override: dict[str, Any]
    ) -> dict[str, Any]:
        key = self.artifact_key(project_id, test_case_id)
        payload = {
            **override,
            "project_id": project_id,
            "test_case_id": test_case_id,
        }
        with self._lock:
            self.test_review_overrides[key] = payload
            self.persist()
        return payload

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.nodes = {
                k: GraphNode.model_validate(v) for k, v in raw.get("nodes", {}).items()
            }
            self.edges = {
                k: GraphEdge.model_validate(v) for k, v in raw.get("edges", {}).items()
            }
            self.projects = raw.get("projects", {})
            self.documents = raw.get("documents", {})
            self.test_cases = raw.get("test_cases", {})
            self.bugs = raw.get("bugs", {})
            self.graph_versions = raw.get("graph_versions", {})
            self.latest_analyses = raw.get("latest_analyses", {})
            self.test_reviews = raw.get("test_reviews", {})
            self.test_review_overrides = raw.get("test_review_overrides", {})
            self.external_knowledge_sources = raw.get("external_knowledge_sources", {})
            logger.info(
                "graph_store_loaded",
                path=str(self.path.resolve()),
                nodes=len(self.nodes),
                edges=len(self.edges),
                projects=len(self.projects),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("graph_store_load_failed", error=str(exc))

    def persist(self) -> None:
        with self._lock:
            payload = {
                "nodes": {k: v.model_dump(mode="json") for k, v in self.nodes.items()},
                "edges": {k: v.model_dump(mode="json") for k, v in self.edges.items()},
                "projects": self.projects,
                "documents": self.documents,
                "test_cases": self.test_cases,
                "bugs": self.bugs,
                "graph_versions": self.graph_versions,
                "latest_analyses": self.latest_analyses,
                "test_reviews": self.test_reviews,
                "test_review_overrides": self.test_review_overrides,
                "external_knowledge_sources": self.external_knowledge_sources,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Compact JSON — analyses can be multi‑MB; indent=2 made deletes rewrite ~30MB+
            # and (with --reload) triggered uvicorn restarts mid-request.
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp.replace(self.path)

    def upsert_node(self, node: GraphNode) -> GraphNode:
        with self._lock:
            existing = self.nodes.get(node.id)
            if existing and existing.provenance.source_type == SourceType.USER_INPUT:
                # Never silently overwrite user-created node facts with inferred data
                if node.provenance.source_type != SourceType.USER_INPUT:
                    logger.info("preserve_user_node", node_id=node.id)
                    return existing
            node.updated_at = utc_now()
            self.nodes[node.id] = node
            self.persist()
            return node

    def upsert_edge(self, edge: GraphEdge) -> GraphEdge:
        with self._lock:
            # Idempotent: same source/target/relationship merges
            for existing in self.edges.values():
                if (
                    existing.source == edge.source
                    and existing.target == edge.target
                    and str(existing.relationship) == str(edge.relationship)
                ):
                    if (
                        existing.provenance.source_type == SourceType.USER_INPUT
                        and edge.provenance.source_type != SourceType.USER_INPUT
                    ):
                        return existing
                    # Prefer non-inferred / higher confidence
                    if existing.provenance.inferred and not edge.provenance.inferred:
                        self.edges[existing.id] = edge.model_copy(
                            update={"id": existing.id}
                        )
                        self.persist()
                        return self.edges[existing.id]
                    return existing
            self.edges[edge.id] = edge
            self.persist()
            return edge

    def delete_node(self, node_id: str) -> bool:
        with self._lock:
            if node_id not in self.nodes:
                return False
            del self.nodes[node_id]
            self.edges = {
                eid: e
                for eid, e in self.edges.items()
                if e.source != node_id and e.target != node_id
            }
            self.persist()
            return True

    def delete_edge(self, edge_id: str) -> bool:
        with self._lock:
            if edge_id not in self.edges:
                return False
            del self.edges[edge_id]
            self.persist()
            return True

    def get_node(self, node_id: str) -> GraphNode | None:
        return self.nodes.get(node_id)

    def get_edge(self, edge_id: str) -> GraphEdge | None:
        return self.edges.get(edge_id)

    def find_nodes(
        self,
        project_id: str,
        *,
        name: str | None = None,
        node_type: NodeType | None = None,
    ) -> list[GraphNode]:
        results = [n for n in self.nodes.values() if n.project_id == project_id]
        if name:
            name_l = name.lower()
            results = [n for n in results if name_l in n.name.lower()]
        if node_type:
            results = [n for n in results if n.type == node_type]
        return results

    def find_node_by_name(self, project_id: str, name: str) -> GraphNode | None:
        name_l = name.lower().strip()
        for n in self.nodes.values():
            if n.project_id == project_id and n.name.lower().strip() == name_l:
                return n
        return None

    def get_project_graph(self, project_id: str) -> SystemFlowGraph:
        project = self.projects.get(project_id, {})
        nodes = [n for n in self.nodes.values() if n.project_id == project_id]
        node_ids = {n.id for n in nodes}
        edges = [
            e
            for e in self.edges.values()
            if e.source in node_ids and e.target in node_ids
        ]
        return SystemFlowGraph(
            project_id=project_id,
            root_node_id=project.get("root_feature_id") or project.get("root_node_id"),
            version=project.get("graph_version", 1),
            nodes=nodes,
            edges=edges,
        )

    def save_project_graph(self, graph: SystemFlowGraph) -> SystemFlowGraph:
        with self._lock:
            # Snapshot version history
            versions = self.graph_versions.setdefault(graph.project_id, [])
            current = self.get_project_graph(graph.project_id)
            if current.nodes or current.edges:
                versions.append(
                    {
                        "version": current.version,
                        "snapshot": current.model_dump(mode="json"),
                        "saved_at": utc_now().isoformat(),
                    }
                )
                # Keep last 20 versions
                self.graph_versions[graph.project_id] = versions[-20:]

            # Remove project nodes/edges then rewrite (user save is authoritative for flow graph)
            existing_ids = {
                n.id for n in self.nodes.values() if n.project_id == graph.project_id
            }
            # Preserve QA artifact nodes (TestCase, Bug, Risk, etc.) not in the saved flow graph
            preserve_types = {
                NodeType.TEST_CASE,
                NodeType.TEST_SUITE,
                NodeType.BUG,
                NodeType.RISK,
                NodeType.REQUIREMENT,
                NodeType.QA_DOCUMENT,
                NodeType.TESTING_TECHNIQUE,
                NodeType.EXPLORATORY_MISSION,
                NodeType.EXTERNAL_SOURCE,
            }
            for nid in list(existing_ids):
                node = self.nodes[nid]
                if node.type in preserve_types and nid not in {
                    n.id for n in graph.nodes
                }:
                    continue
                if nid not in {n.id for n in graph.nodes}:
                    self.delete_node(nid)

            for node in graph.nodes:
                node.project_id = graph.project_id
                if not node.provenance.source_type:
                    node.provenance = Provenance(
                        source_type=SourceType.USER_INPUT, inferred=False
                    )
                self.nodes[node.id] = node

            # Replace flow edges among flow nodes
            flow_ids = {n.id for n in graph.nodes}
            self.edges = {
                eid: e
                for eid, e in self.edges.items()
                if not (e.source in flow_ids and e.target in flow_ids)
            }
            for edge in graph.edges:
                self.edges[edge.id] = edge

            project = self.projects.setdefault(
                graph.project_id, {"id": graph.project_id}
            )
            project["root_feature_id"] = graph.root_node_id
            project["root_node_id"] = graph.root_node_id
            project["graph_version"] = graph.version + (
                1 if current.nodes or current.edges else 0
            )
            project["updated_at"] = utc_now().isoformat()
            graph.version = project["graph_version"]
            graph.updated_at = utc_now()
            self.persist()
            return graph

    def neighbors(
        self,
        node_id: str,
        *,
        direction: str = "outgoing",
        relationship: str | None = None,
    ) -> list[tuple[GraphEdge, GraphNode]]:
        results: list[tuple[GraphEdge, GraphNode]] = []
        for edge in self.edges.values():
            if relationship and str(edge.relationship) != str(relationship):
                continue
            if direction in ("outgoing", "both") and edge.source == node_id:
                target = self.nodes.get(edge.target)
                if target:
                    results.append((edge, target))
            if direction in ("incoming", "both") and edge.target == node_id:
                source = self.nodes.get(edge.source)
                if source:
                    results.append((edge, source))
        return results

    def discover_paths(
        self,
        project_id: str,
        root_id: str,
        *,
        max_depth: int = 8,
    ) -> list[GraphPath]:
        """DFS leaf-path discovery from root."""
        if root_id not in self.nodes:
            return []
        paths: list[GraphPath] = []

        def dfs(
            current: str,
            names: list[str],
            ids: list[str],
            rels: list[str],
            depth: int,
            failure: bool,
            external: bool,
        ) -> None:
            children = [
                (e, n)
                for e, n in self.neighbors(current, direction="outgoing")
                if n.project_id == project_id and n.id not in ids
            ]
            if not children or depth >= max_depth:
                paths.append(
                    GraphPath(
                        node_ids=ids[:],
                        node_names=names[:],
                        relationships=rels[:],
                        is_failure_path=failure,
                        includes_external_dependency=external,
                    )
                )
                return
            for edge, child in children:
                dfs(
                    child.id,
                    names + [child.name],
                    ids + [child.id],
                    rels + [str(edge.relationship)],
                    depth + 1,
                    failure
                    or child.is_failure_path
                    or child.type == NodeType.FAILURE_PATH,
                    external
                    or child.is_external_dependency
                    or child.type
                    in (NodeType.EXTERNAL_DEPENDENCY, NodeType.THIRD_PARTY_PROVIDER),
                )

        root = self.nodes[root_id]
        dfs(
            root_id,
            [root.name],
            [root_id],
            [],
            0,
            root.is_failure_path,
            root.is_external_dependency,
        )
        return paths

    def impact_subgraph(self, node_id: str, *, max_depth: int = 4) -> dict[str, Any]:
        if node_id not in self.nodes:
            return {
                "changed_node": node_id,
                "direct": [],
                "indirect": [],
                "paths": [],
            }
        direct: list[str] = []
        indirect: list[str] = []
        reasoning: list[str] = []
        visited = {node_id}
        frontier = [(node_id, 0, [self.nodes[node_id].name])]
        while frontier:
            current, depth, path = frontier.pop(0)
            if depth >= max_depth:
                continue
            for edge, neighbor in self.neighbors(current, direction="both"):
                if neighbor.id in visited:
                    continue
                visited.add(neighbor.id)
                new_path = path + [neighbor.name]
                reasoning.append(" → ".join(new_path) + f" [{edge.relationship}]")
                if depth == 0:
                    direct.append(neighbor.name)
                else:
                    indirect.append(neighbor.name)
                frontier.append((neighbor.id, depth + 1, new_path))
        return {
            "changed_node": self.nodes[node_id].name,
            "direct": direct,
            "indirect": indirect,
            "paths": reasoning,
        }

    # --- Project / document / artifact helpers ---

    def create_project(
        self, name: str, description: str = "", root_feature: str | None = None
    ) -> dict[str, Any]:
        pid = new_id("project")
        root_id = None
        if root_feature:
            root = GraphNode(
                id=new_id("feature"),
                type=NodeType.FEATURE,
                name=root_feature,
                description=f"Root feature for {name}",
                project_id=pid,
                is_critical=True,
                criticality=Priority.HIGH,
                provenance=Provenance(
                    source_type=SourceType.USER_INPUT, inferred=False, confidence=1.0
                ),
            )
            self.nodes[root.id] = root
            root_id = root.id
        project = {
            "id": pid,
            "name": name,
            "description": description,
            "root_feature_id": root_id,
            "root_node_id": root_id,
            "graph_version": 1,
            "created_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat(),
        }
        self.projects[pid] = project
        self.persist()
        return project

    def list_projects(self) -> list[dict[str, Any]]:
        return list(self.projects.values())

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self.projects.get(project_id)

    def delete_project(self, project_id: str) -> dict[str, int] | None:
        """
        Remove every resource belonging only to this project.

        Returns deletion counts, or None if the project does not exist.
        Does not touch other projects' data.
        """
        with self._lock:
            if project_id not in self.projects:
                return None

            node_ids = {
                nid for nid, node in self.nodes.items() if node.project_id == project_id
            }
            nodes_removed = len(node_ids)

            edge_ids = [
                eid
                for eid, edge in self.edges.items()
                if edge.source in node_ids or edge.target in node_ids
            ]
            edges_removed = len(edge_ids)
            for eid in edge_ids:
                del self.edges[eid]
            for nid in node_ids:
                del self.nodes[nid]

            doc_ids = [
                did
                for did, doc in self.documents.items()
                if doc.get("project_id") == project_id
            ]
            documents_removed = len(doc_ids)
            for did in doc_ids:
                del self.documents[did]

            test_keys = [
                key
                for key, case in self.test_cases.items()
                if case.get("project_id") == project_id
            ]
            tests_removed = len(test_keys)
            for key in test_keys:
                del self.test_cases[key]

            bug_keys = [
                key
                for key, bug in self.bugs.items()
                if bug.get("project_id") == project_id
            ]
            bugs_removed = len(bug_keys)
            for key in bug_keys:
                del self.bugs[key]

            review_keys = [
                key
                for key, review in self.test_reviews.items()
                if review.get("project_id") == project_id
            ]
            for key in review_keys:
                del self.test_reviews[key]

            override_keys = [
                key
                for key in self.test_review_overrides
                if self.test_review_overrides[key].get("project_id") == project_id
            ]
            for key in override_keys:
                del self.test_review_overrides[key]

            versions = self.graph_versions.pop(project_id, None) or []
            analysis = self.latest_analyses.pop(project_id, None)
            # Coverage / gaps / traces live inside latest analysis (no separate table).
            coverage_removed = 1 if analysis else 0

            ext_keys = [
                sid
                for sid, src in self.external_knowledge_sources.items()
                if src.get("qa_project_id") == project_id
            ]
            for sid in ext_keys:
                del self.external_knowledge_sources[sid]

            del self.projects[project_id]
            self.persist()

            logger.info(
                "project_deleted",
                project_id=project_id,
                nodes=nodes_removed,
                edges=edges_removed,
                documents=documents_removed,
                tests=tests_removed,
                bugs=bugs_removed,
                graph_versions=len(versions),
                analysis=bool(analysis),
            )
            return {
                "nodes": nodes_removed,
                "edges": edges_removed,
                "documents": documents_removed,
                "tests": tests_removed,
                "bugs": bugs_removed,
                "coverage": coverage_removed,
                "graph_versions": len(versions),
                "analyses": 1 if analysis else 0,
            }


class MongoGraphStore(InMemoryGraphStore):
    """Mongo-backed graph/domain store while preserving in-memory API contracts."""

    def __init__(self, path: str | None = None) -> None:
        super().__init__(path=path)

    def _load(self) -> None:
        self.nodes = {}
        self.edges = {}
        self.projects = {}
        self.documents = {}
        self.test_cases = {}
        self.bugs = {}
        self.graph_versions = {}
        self.latest_analyses = {}
        self.test_reviews = {}
        self.test_review_overrides = {}
        self.external_knowledge_sources = {}
        try:
            projects = list(get_qa_projects_collection_sync().find({}))
        except Exception as exc:  # noqa: BLE001
            logger.warning("mongo_graph_store_load_failed", error=str(exc))
            return
        if not projects:
            return

        self.projects = {p["project_id"]: p["project"] for p in projects}

        self.nodes = {}
        for raw in get_qa_nodes_collection_sync().find({}):
            self.nodes[raw["node_id"]] = GraphNode.model_validate(raw["node"])

        self.edges = {}
        for raw in get_qa_edges_collection_sync().find({}):
            self.edges[raw["edge_id"]] = GraphEdge.model_validate(raw["edge"])

        chunks_by_doc: dict[str, list[dict[str, Any]]] = {}
        for chunk in get_qa_document_chunks_collection_sync().find({}):
            doc_id = str(chunk.get("document_id") or "")
            if not doc_id:
                continue
            payload = dict(chunk.get("chunk") or {})
            if payload:
                chunks_by_doc.setdefault(doc_id, []).append(payload)

        self.documents = {}
        for doc in get_qa_documents_collection_sync().find({}):
            payload = dict(doc.get("document") or {})
            doc_id = str(payload.get("id") or doc.get("document_id") or "")
            if doc_id:
                payload["chunks"] = chunks_by_doc.get(doc_id, [])
                self.documents[doc_id] = payload

        self.test_cases = {}
        for row in get_qa_test_cases_collection_sync().find({}):
            payload = dict(row.get("test_case") or {})
            project_id = str(row.get("project_id") or payload.get("project_id") or "")
            test_case_id = str(row.get("test_case_id") or payload.get("test_case_id") or "")
            if not project_id or not test_case_id:
                continue
            self.test_cases[self.artifact_key(project_id, test_case_id)] = payload

        self.bugs = {}
        for row in get_qa_bugs_collection_sync().find({}):
            payload = dict(row.get("bug") or {})
            project_id = str(row.get("project_id") or payload.get("project_id") or "")
            bug_id = str(row.get("bug_id") or payload.get("bug_id") or "")
            if not project_id or not bug_id:
                continue
            self.bugs[self.artifact_key(project_id, bug_id)] = payload

        self.graph_versions = {}
        for row in get_qa_graph_versions_collection_sync().find({}):
            project_id = str(row.get("project_id") or "")
            if not project_id:
                continue
            self.graph_versions.setdefault(project_id, []).append(
                {
                    "version": row.get("version"),
                    "snapshot": row.get("snapshot"),
                    "saved_at": row.get("saved_at"),
                }
            )

        self.latest_analyses = {}
        for row in get_qa_analyses_collection_sync().find({"is_latest": True}):
            project_id = str(row.get("project_id") or "")
            analysis = dict(row.get("analysis") or {})
            if project_id:
                self.latest_analyses[project_id] = analysis

        self.test_reviews = {}
        for row in get_qa_test_reviews_collection_sync().find({}):
            payload = dict(row.get("review") or {})
            project_id = str(row.get("project_id") or payload.get("project_id") or "")
            test_case_id = str(row.get("test_case_id") or payload.get("test_case_id") or "")
            if project_id and test_case_id:
                self.test_reviews[self.artifact_key(project_id, test_case_id)] = payload

        self.test_review_overrides = {}
        for row in get_qa_test_review_overrides_collection_sync().find({}):
            payload = dict(row.get("override") or {})
            project_id = str(row.get("project_id") or payload.get("project_id") or "")
            test_case_id = str(row.get("test_case_id") or payload.get("test_case_id") or "")
            if project_id and test_case_id:
                self.test_review_overrides[self.artifact_key(project_id, test_case_id)] = payload

        self.external_knowledge_sources = {}
        for row in get_qa_external_knowledge_sources_collection_sync().find({}):
            payload = dict(row.get("source") or {})
            source_id = str(row.get("source_id") or payload.get("source_id") or "")
            if source_id:
                self.external_knowledge_sources[source_id] = payload

        logger.info(
            "mongo_graph_store_loaded",
            projects=len(self.projects),
            nodes=len(self.nodes),
            edges=len(self.edges),
            documents=len(self.documents),
            tests=len(self.test_cases),
            bugs=len(self.bugs),
        )

    def persist(self) -> None:
        self._persist_mongo()

    def _refresh_projects_from_mongo(self) -> None:
        """Refresh project cache so external seeds are visible without restart."""
        try:
            projects = list(get_qa_projects_collection_sync().find({}))
        except Exception as exc:  # noqa: BLE001
            logger.warning("mongo_project_refresh_failed", error=str(exc))
            return
        self.projects = {p["project_id"]: p["project"] for p in projects}

    def list_projects(self) -> list[dict[str, Any]]:
        self._refresh_projects_from_mongo()
        return super().list_projects()

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        self._refresh_projects_from_mongo()
        return super().get_project(project_id)

    def _sync_collection(
        self, collection: Any, docs: list[dict[str, Any]], key_field: str
    ) -> None:
        existing_keys = set()
        for doc in docs:
            key = doc.get(key_field)
            if key is None:
                continue
            existing_keys.add(key)
            collection.replace_one({key_field: key}, doc, upsert=True)
        if existing_keys:
            collection.delete_many({key_field: {"$nin": list(existing_keys)}})
        else:
            collection.delete_many({})

    def _persist_mongo(self) -> None:
        projects_docs = []
        for project_id, project in self.projects.items():
            projects_docs.append(
                {"project_id": project_id, "project": project, "_id": project_id}
            )
        self._sync_collection(get_qa_projects_collection_sync(), projects_docs, "project_id")

        node_docs = []
        for node_id, node in self.nodes.items():
            node_dump = node.model_dump(mode="json")
            node_docs.append(
                {
                    "_id": node_id,
                    "node_id": node_id,
                    "project_id": node.project_id,
                    "type": str(node.type.value),
                    "name_lc": node.name.lower().strip(),
                    "node": node_dump,
                }
            )
        self._sync_collection(get_qa_nodes_collection_sync(), node_docs, "node_id")

        edge_docs = []
        for edge_id, edge in self.edges.items():
            source_node = self.nodes.get(edge.source)
            project_id = source_node.project_id if source_node else None
            edge_docs.append(
                {
                    "_id": edge_id,
                    "edge_id": edge_id,
                    "project_id": project_id,
                    "source_node_id": edge.source,
                    "target_node_id": edge.target,
                    "relationship": str(edge.relationship),
                    "edge": edge.model_dump(mode="json"),
                }
            )
        self._sync_collection(get_qa_edges_collection_sync(), edge_docs, "edge_id")

        documents_docs = []
        chunks_docs: list[dict[str, Any]] = []
        for document_id, document in self.documents.items():
            documents_docs.append(
                {
                    "_id": document_id,
                    "document_id": document_id,
                    "project_id": document.get("project_id"),
                    "filename": document.get("filename"),
                    "content_hash": document.get("content_hash"),
                    "document": document,
                }
            )
            for idx, chunk in enumerate(document.get("chunks", [])):
                chunk_id = str(chunk.get("id") or "")
                if not chunk_id:
                    continue
                metadata = chunk.get("metadata") or {}
                chunks_docs.append(
                    {
                        "_id": chunk_id,
                        "chunk_id": chunk_id,
                        "project_id": chunk.get("project_id") or document.get("project_id"),
                        "document_id": document_id,
                        "source_type": metadata.get("source_type"),
                        "feature": metadata.get("feature"),
                        "chunk_index": idx,
                        "chunk": chunk,
                    }
                )
        self._sync_collection(
            get_qa_documents_collection_sync(), documents_docs, "document_id"
        )
        self._sync_collection(
            get_qa_document_chunks_collection_sync(), chunks_docs, "chunk_id"
        )

        test_case_docs = []
        for payload in self.test_cases.values():
            project_id = str(payload.get("project_id") or "")
            test_case_id = str(payload.get("test_case_id") or "")
            if not project_id or not test_case_id:
                continue
            key = self.artifact_key(project_id, test_case_id)
            test_case_docs.append(
                {
                    "_id": key,
                    "key": key,
                    "project_id": project_id,
                    "test_case_id": test_case_id,
                    "generation_method": payload.get("generation_method"),
                    "updated_at": payload.get("updated_at"),
                    "test_case": payload,
                }
            )
        self._sync_collection(get_qa_test_cases_collection_sync(), test_case_docs, "key")

        bug_docs = []
        for payload in self.bugs.values():
            project_id = str(payload.get("project_id") or "")
            bug_id = str(payload.get("bug_id") or "")
            if not project_id or not bug_id:
                continue
            key = self.artifact_key(project_id, bug_id)
            bug_docs.append(
                {
                    "_id": key,
                    "key": key,
                    "project_id": project_id,
                    "bug_id": bug_id,
                    "created_at": payload.get("created_at"),
                    "bug": payload,
                }
            )
        self._sync_collection(get_qa_bugs_collection_sync(), bug_docs, "key")

        analysis_docs = []
        for project_id, analysis in self.latest_analyses.items():
            analysis_id = str(analysis.get("analysis_id") or f"latest-{project_id}")
            analysis_docs.append(
                {
                    "_id": analysis_id,
                    "analysis_id": analysis_id,
                    "project_id": project_id,
                    "is_latest": True,
                    "created_at": analysis.get("created_at") or analysis.get("updated_at"),
                    "updated_at": analysis.get("updated_at"),
                    "analysis": analysis,
                }
            )
        self._sync_collection(get_qa_analyses_collection_sync(), analysis_docs, "analysis_id")

        review_docs = []
        for payload in self.test_reviews.values():
            project_id = str(payload.get("project_id") or "")
            test_case_id = str(payload.get("test_case_id") or "")
            if not project_id or not test_case_id:
                continue
            key = self.artifact_key(project_id, test_case_id)
            review_docs.append(
                {
                    "_id": key,
                    "key": key,
                    "project_id": project_id,
                    "test_case_id": test_case_id,
                    "updated_at": payload.get("updated_at"),
                    "review": payload,
                }
            )
        self._sync_collection(get_qa_test_reviews_collection_sync(), review_docs, "key")

        override_docs = []
        for payload in self.test_review_overrides.values():
            project_id = str(payload.get("project_id") or "")
            test_case_id = str(payload.get("test_case_id") or "")
            if not project_id or not test_case_id:
                continue
            key = self.artifact_key(project_id, test_case_id)
            override_docs.append(
                {
                    "_id": key,
                    "key": key,
                    "project_id": project_id,
                    "test_case_id": test_case_id,
                    "override_timestamp": payload.get("override_timestamp"),
                    "override": payload,
                }
            )
        self._sync_collection(
            get_qa_test_review_overrides_collection_sync(), override_docs, "key"
        )

        graph_version_docs = []
        for project_id, versions in self.graph_versions.items():
            for row in versions:
                version = int(row.get("version") or 0)
                key = f"{project_id}::{version}"
                graph_version_docs.append(
                    {
                        "_id": key,
                        "key": key,
                        "project_id": project_id,
                        "version": version,
                        "saved_at": row.get("saved_at"),
                        "snapshot": row.get("snapshot"),
                    }
                )
        self._sync_collection(
            get_qa_graph_versions_collection_sync(), graph_version_docs, "key"
        )

        source_docs = []
        for source_id, source in self.external_knowledge_sources.items():
            source_docs.append(
                {
                    "_id": source_id,
                    "source_id": source_id,
                    "qa_project_id": source.get("qa_project_id"),
                    "cloud_id": source.get("cloud_id"),
                    "source_type": source.get("source_type"),
                    "external_id": source.get("external_id"),
                    "last_synced_at": source.get("last_synced_at"),
                    "source": source,
                }
            )
        self._sync_collection(
            get_qa_external_knowledge_sources_collection_sync(),
            source_docs,
            "source_id",
        )


class Neo4jGraphStore:
    """Optional Neo4j-backed store. Delegates to in-memory if Neo4j unavailable."""

    def __init__(self, fallback: InMemoryGraphStore) -> None:
        self.fallback = fallback
        self._driver = None
        settings = get_settings()
        if not settings.neo4j_enabled:
            return
        try:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            self._driver.verify_connectivity()
            logger.info("neo4j_connected", uri=settings.neo4j_uri)
        except Exception as exc:  # noqa: BLE001
            logger.warning("neo4j_unavailable_using_memory", error=str(exc))
            self._driver = None

    def sync_node(self, node: GraphNode) -> None:
        if not self._driver:
            return
        cypher = """
        MERGE (n:Entity {id: $id})
        SET n += $props, n:`{label}`
        """.replace("{label}", node.type.value)
        props = {
            "name": node.name,
            "description": node.description,
            "project_id": node.project_id,
            "type": node.type.value,
            "is_failure_path": node.is_failure_path,
            "is_external_dependency": node.is_external_dependency,
            "is_critical": node.is_critical,
        }
        with self._driver.session() as session:
            session.run(cypher, id=node.id, props=props)

    def sync_edge(self, edge: GraphEdge) -> None:
        if not self._driver:
            return
        rel = str(edge.relationship)
        if not rel.replace("_", "").isalnum():
            rel = RelationshipType.RELATED_TO.value
        cypher = f"""
        MATCH (a:Entity {{id: $source}})
        MATCH (b:Entity {{id: $target}})
        MERGE (a)-[r:{rel}]->(b)
        SET r.id = $id
        """
        with self._driver.session() as session:
            session.run(cypher, source=edge.source, target=edge.target, id=edge.id)

    def close(self) -> None:
        if self._driver:
            self._driver.close()


_store: InMemoryGraphStore | None = None
_neo4j: Neo4jGraphStore | None = None


def get_graph_store() -> InMemoryGraphStore:
    global _store
    if _store is None:
        settings = get_settings()
        if not settings.mongo_enabled:
            raise RuntimeError("Mongo graph store requires MONGO_ENABLED=true")
        _store = MongoGraphStore()
    return _store


def get_neo4j_store() -> Neo4jGraphStore:
    global _neo4j
    if _neo4j is None:
        _neo4j = Neo4jGraphStore(get_graph_store())
    return _neo4j


