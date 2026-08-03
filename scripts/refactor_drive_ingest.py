
FILEPATH = r"C:\Users\compg\Desktop\top-code workspace\gmail-agent\tools\gmail_audit\drive_ingest_runtime.py"

with open(FILEPATH, encoding="utf-8") as f:
    lines = f.read().splitlines(keepends=True)
print(f"Read {len(lines)} lines")

def rep(start, end, text):
    global lines
    if text and not text.endswith("\n"):
        text += "\n"
    nl = text.splitlines(keepends=True)
    old_sz = sum(len(l) for l in lines[start:end])
    print(f"  L{start+1}-{end} ({old_sz}B -> {len(text)}B)")
    lines[start:end] = nl

# ================================================================
# 1. REFACTOR _normalize_candidate (L655-L910 = indices 654-909)
# ================================================================

NORM_META = r"""    def _normalize_candidate_meta(
        self, candidate: DriveIngestCandidate, *, observed_at: str
    ) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        document_id = stable_id("gdoc", candidate.drive_item_id)
        content_sha = ""
        blob_path = ""
        text_content = ""
        summary_text = ""
        extraction_confidence = 0.0
        extraction_status = "skipped_folder" if candidate.is_folder else "pending"
        download_mime_type = candidate.mime_type
        extraction_method = ""
        extraction_metadata: dict[str, Any] = {"warnings": []}

        events.append(
            self._build_event_row(
                case_id="",
                event_type="drive_lane_classified",
                summary_text=f"Drive lane {candidate.lane} dla {candidate.title}",
                occurred_at=observed_at,
                payload={
                    "drive_item_id": candidate.drive_item_id,
                    "lane": candidate.lane,
                    "document_kind": candidate.document_kind,
                    "scope": candidate.scope,
                },
                source_refs=[{"type": "gdrive", "source_ref": candidate.source_ref}],
            )
        )

        skip_reason = self._drive_skip_reason(candidate)
        if skip_reason:
            extraction_status = "skipped_policy"
            summary_text = f"Drive ingest skipped: {skip_reason}"
            events.append(
                self._build_event_row(
                    case_id="",
                    event_type="drive_document_skipped",
                    summary_text=summary_text,
                    occurred_at=observed_at,
                    payload={
                        "drive_item_id": candidate.drive_item_id,
                        "skip_reason": skip_reason,
                        "size_bytes": int(candidate.size_bytes or 0),
                    },
                    source_refs=[{"type": "gdrive", "source_ref": candidate.source_ref}],
                )
            )
        elif not candidate.is_folder and candidate.document_kind != "media_asset":
            try:
                downloaded = self.client.download_content(
                    candidate.metadata,
                    max_bytes=self.settings.google_drive_max_download_bytes,
                )
                raw_bytes = downloaded.data
                download_mime_type = downloaded.mime_type
                content_sha = hashlib.sha256(raw_bytes).hexdigest()
                blob_path = self._write_blob(content_sha, raw_bytes)
                parse_config = build_parse_config_from_settings(self.settings)
                parse_result = parse_attachment_document(
                    raw_bytes,
                    mime_type=download_mime_type,
                    file_name=candidate.title,
                    docling_enabled=parse_config.docling_enabled,
                    unstructured_enabled=parse_config.unstructured_enabled,
                    parser_chain=parse_config.resolved_chain(),
                    docling_options=dict(parse_config.docling_options),
                    structured_facts_enabled=parse_config.structured_facts_enabled,
                )
                extraction = parse_result.to_extraction_dict()
                text_content = str(extraction.get("extracted_text") or "")
                extraction_confidence = float(extraction.get("extraction_confidence") or 0.0)
                extraction_metadata = dict(extraction.get("metadata") or {})
                extraction_status = map_extraction_status(
                    extraction_status=str(extraction.get("extraction_status") or ""),
                    title=candidate.title,
                    extracted_text=text_content,
                )
                extraction_method = str(extraction.get("extraction_method") or "")
                summary_text = summarize_document_text(text_content, file_name=candidate.title)
            except GoogleDriveClientError as exc:
                extraction_status = "blocked" if "max bytes" in str(exc).lower() else "failed"
                summary_text = f"Drive ingest: {str(exc)}"
                events.append(
                    self._build_event_row(
                        case_id="",
                        event_type="drive_extraction_failed",
                        summary_text=f"Nie udalo sie pobrac/odczytac {candidate.title}",
                        occurred_at=observed_at,
                        payload={"error": str(exc), "drive_item_id": candidate.drive_item_id},
                        source_refs=[{"type": "gdrive", "source_ref": candidate.source_ref}],
                    )
                )
        elif candidate.document_kind == "media_asset":
            extraction_status = "skipped_binary"
            summary_text = f"Media asset present: {candidate.title}"
        else:
            summary_text = f"Drive folder present: {candidate.title}"

        return {
            "events": events,
            "document_id": document_id,
            "content_sha": content_sha,
            "blob_path": blob_path,
            "text_content": text_content,
            "summary_text": summary_text,
            "extraction_confidence": extraction_confidence,
            "extraction_status": extraction_status,
            "download_mime_type": download_mime_type,
            "extraction_method": extraction_method,
            "extraction_metadata": extraction_metadata,
            "skip_reason": skip_reason or "",
        }

"""

NORM_FACTS = r"""    def _normalize_candidate_facts(
        self,
        candidate: DriveIngestCandidate,
        *,
        document_id: str,
        text_content: str,
        observed_at: str,
    ) -> dict[str, Any]:
        extracted_facts = extract_drive_facts(
            candidate,
            document_id=document_id,
            text=text_content,
            observed_at=observed_at,
            source_ref=candidate.source_ref,
        )
        link_result = link_drive_candidate(candidate, extracted_facts=extracted_facts, store=self.store)
        case_id = str(link_result.get("case_id") or "").strip()
        case_key = str(link_result.get("case_key") or candidate.probable_case_key or "").strip()
        linkage_status = str(link_result.get("linkage_status") or "unresolved_candidate")
        link_confidence = float(link_result.get("confidence") or 0.0)
        if not case_id and case_key and candidate.scope == "case_specific":
            case_id = stable_id("case", case_key)
            if linkage_status == "unresolved_candidate":
                linkage_status = "deterministic"
                link_confidence = max(link_confidence, 0.97)
                link_result["reasons"] = list(link_result.get("reasons") or []) + ["probable_case_key_seeded_case"]

        case_seed_row = {}
        if case_id:
            case_seed_row = build_drive_case_seed_row(
                existing_case=self.store.fetch_case(case_id) or {},
                case_id=case_id,
                case_key=case_key,
                candidate=candidate,
                facts=extracted_facts,
                observed_at=observed_at,
            )

        fact_rows = [
            build_drive_fact_row(
                item,
                document_id=document_id,
                case_id=case_id,
                probable_case_key=case_key,
                observed_at=observed_at,
            )
            for item in extracted_facts
        ]

        chunk_rows = self._build_drive_chunk_rows(
            case_id=case_id,
            document_id=document_id,
            file_name=candidate.title,
            text=text_content,
            observed_at=observed_at,
        )

        return {
            "extracted_facts": extracted_facts,
            "link_result": link_result,
            "case_id": case_id,
            "case_key": case_key,
            "linkage_status": linkage_status,
            "link_confidence": link_confidence,
            "case_seed_row": case_seed_row,
            "fact_rows": fact_rows,
            "chunk_rows": chunk_rows,
        }

"""

NORM_EVENTS = r"""    def _normalize_candidate_events(
        self,
        candidate: DriveIngestCandidate,
        *,
        case_id: str,
        document_id: str,
        linkage_status: str,
        link_result: dict[str, Any],
        extracted_facts: list[dict[str, Any]],
        observed_at: str,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        events.append(
            self._build_event_row(
                case_id=case_id,
                event_type="drive_document_ingested",
                summary_text=f"Drive document ingested: {candidate.title}",
                occurred_at=observed_at,
                payload={
                    "document_id": document_id,
                    "lane": candidate.lane,
                    "document_kind": candidate.document_kind,
                    "scope": candidate.scope,
                    "linkage_status": linkage_status,
                },
                source_refs=[{"type": "gdrive", "source_ref": candidate.source_ref}],
            )
        )
        if link_result.get("case_key") or link_result.get("case_id"):
            events.append(
                self._build_event_row(
                    case_id=case_id,
                    event_type="drive_case_link_candidate",
                    summary_text=f"Drive case link {linkage_status} dla {candidate.title}",
                    occurred_at=observed_at,
                    payload=link_result,
                    source_refs=[{"type": "gdrive", "source_ref": candidate.source_ref}],
                )
            )
        conflicts = detect_drive_conflicts(extracted_facts)
        for conflict in conflicts:
            events.append(
                self._build_event_row(
                    case_id=case_id,
                    event_type="drive_conflict_detected",
                    summary_text=conflict,
                    occurred_at=observed_at,
                    payload={"document_id": document_id, "conflict": conflict},
                    source_refs=[{"type": "gdrive", "source_ref": candidate.source_ref}],
                )
            )
        return events

"""

THIN_NORMALIZE = r"""    def _normalize_candidate(self, candidate: DriveIngestCandidate, *, observed_at: str) -> dict[str, Any]:
        meta = self._normalize_candidate_meta(candidate, observed_at=observed_at)
        facts = self._normalize_candidate_facts(
            candidate,
            document_id=meta["document_id"],
            text_content=meta["text_content"],
            observed_at=observed_at,
        )
        events = meta["events"]
        events.extend(
            self._normalize_candidate_events(
                candidate,
                case_id=facts["case_id"],
                document_id=meta["document_id"],
                linkage_status=facts["linkage_status"],
                link_result=facts["link_result"],
                extracted_facts=facts["extracted_facts"],
                observed_at=observed_at,
            )
        )

        record = DriveDocumentRecord(
            document_id=meta["document_id"],
            drive_item_id=candidate.drive_item_id,
            title=candidate.title,
            mime_type=candidate.mime_type,
            folder_path=candidate.folder_path,
            source_ref=candidate.source_ref,
            lane=candidate.lane,
            document_kind=candidate.document_kind,
            scope=candidate.scope,
            extraction_status=meta["extraction_status"],
            linkage_status=facts["linkage_status"],
            case_id=facts["case_id"],
            probable_case_key=facts["case_key"],
            classification_confidence=float(candidate.classification_confidence or 0.0),
            extraction_confidence=meta["extraction_confidence"],
            link_confidence=facts["link_confidence"],
            download_mime_type=meta["download_mime_type"],
            content_sha256=meta["content_sha"],
            blob_path=meta["blob_path"],
            text_content=meta["text_content"],
            summary_text=meta["summary_text"],
            metadata={
                "parent_drive_item_id": candidate.parent_drive_item_id,
                "is_folder": candidate.is_folder,
                "size_bytes": candidate.size_bytes,
                "modified_time": candidate.modified_time,
                "link_reasons": list(facts["link_result"].get("reasons") or []),
                "matched_facts": list(facts["link_result"].get("matched_facts") or []),
                "extraction_method": meta["extraction_method"],
                "parser_stack": list(build_parse_config_from_settings(self.settings).resolved_chain()),
                "parser_id": str(meta["extraction_metadata"].get("parser_id") or ""),
                "structured_parse": bool(meta["extraction_metadata"].get("structured")),
                "docling_used": str(meta["extraction_method"]).startswith("docling")
                or str(meta["extraction_metadata"].get("parser_id") or "") == "docling",
                "ocr_used": "ocr" in str(meta["extraction_method"]).lower(),
                "page_count": int(meta["extraction_metadata"].get("page_count") or 0),
                "table_count": int(meta["extraction_metadata"].get("table_count") or 0),
                "warnings": list(meta["extraction_metadata"].get("warnings") or []),
                "fallback_reason": ""
                if str(meta["extraction_method"]).startswith("docling") or not self.docling_enabled
                else "; ".join(list(meta["extraction_metadata"].get("warnings") or [])[:2]),
            },
        )
        document_row = build_drive_document_row(record, observed_at=observed_at)

        graph_upsert = self._build_graph_upsert(record.to_dict(), facts=facts["fact_rows"])
        existing_document = self.store.fetch_drive_document_by_item_id(candidate.drive_item_id)
        change_kind = "drive_document_updated" if existing_document else "drive_document_added"
        return {
            "change_kind": change_kind,
            "source_ref": {
                "file_id": candidate.drive_item_id,
                "change_id": candidate.drive_item_id,
                "revision_id": str(candidate.modified_time or candidate.drive_item_id),
                "modified_time": str(candidate.modified_time or observed_at),
                "source_ref": candidate.source_ref,
            },
            "signal_summary_pl": f"Drive dokument {candidate.title} ({candidate.document_kind})",
            "document_row": document_row,
            "chunk_rows": facts["chunk_rows"],
            "fact_rows": facts["fact_rows"],
            "event_rows": events,
            "graph_upsert": {"nodes": list(graph_upsert.nodes), "edges": list(graph_upsert.edges)},
            "case_seed_row": facts["case_seed_row"],
            "case_id": facts["case_id"],
            "case_key": facts["case_key"],
            "linkage_status": facts["linkage_status"],
            "link_reasons": list(facts["link_result"].get("reasons") or []),
            "conflicts": detect_drive_conflicts(facts["extracted_facts"]),
        }

"""

print("Applying refactoring 1/3: _normalize_candidate")
rep(654, 910, NORM_META + NORM_FACTS + NORM_EVENTS + THIN_NORMALIZE)


# ================================================================
# 2. REFACTOR _build_graph_upsert (L1044-L1356 = indices 1043-1355)
# ================================================================

GRAPH_NODES = r"""    def _build_graph_nodes(
        self, record: dict[str, Any], *, facts: list[dict[str, Any]], observed_at: str, source_ref: str
    ) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        document_node = build_graph_node(
            node_type="Document",
            natural_key=str(record.get("document_id") or ""),
            title=str(record.get("title") or record.get("file_name") or ""),
            source="gdrive",
            source_ref=source_ref,
            confidence=float(record.get("classification_confidence") or 0.0),
            payload={"document_kind": record.get("document_kind"), "lane": record.get("lane"), "scope": record.get("scope")},
            observed_at=observed_at,
        )
        nodes.append(document_node)

        case_id = str(record.get("case_id") or "").strip()
        kind_node = None
        kind_node_type = KIND_TO_NODE_TYPE.get(str(record.get("document_kind") or ""), "Document")
        if kind_node_type != "Document":
            kind_node = build_graph_node(
                node_type=kind_node_type,
                natural_key=str(record.get("document_id") or ""),
                title=str(record.get("title") or record.get("file_name") or ""),
                source="gdrive",
                source_ref=source_ref,
                confidence=float(record.get("classification_confidence") or 0.0),
                payload={"document_id": record.get("document_id"), "document_kind": record.get("document_kind")},
                observed_at=observed_at,
            )
            nodes.append(kind_node)

        case_node = None
        if case_id:
            case_node = build_graph_node(
                node_type="Case",
                natural_key=case_id,
                title=str(record.get("probable_case_key") or case_id),
                source="gdrive",
                source_ref=source_ref,
                confidence=float(record.get("link_confidence") or 0.0),
                payload={"case_key": record.get("probable_case_key")},
                observed_at=observed_at,
            )
            nodes.append(case_node)

        manufacturer = infer_manufacturer(str(record.get("title") or "") + " " + str(record.get("summary_text") or ""))
        manufacturer_node = None
        if manufacturer:
            manufacturer_node = build_graph_node(
                node_type="Manufacturer",
                natural_key=manufacturer.lower(),
                title=manufacturer,
                source="gdrive",
                source_ref=source_ref,
                confidence=0.82,
                payload={},
                observed_at=observed_at,
            )
            nodes.append(manufacturer_node)

        offer_family_value = first_fact_value(facts, "offer_family")
        offer_family_node = None
        if offer_family_value:
            offer_family_node = build_graph_node(
                node_type="OfferFamily",
                natural_key=offer_family_value.lower(),
                title=offer_family_value,
                source="gdrive",
                source_ref=source_ref,
                confidence=0.86,
                payload={},
                observed_at=observed_at,
            )
            nodes.append(offer_family_node)

        model_nodes: list[dict[str, Any]] = []
        for model_value in collect_fact_values(facts, {"device_model", "device_model_bundle", "model_bundle"}):
            model_node = build_graph_node(
                node_type="Model",
                natural_key=model_value.lower(),
                title=model_value,
                source="gdrive",
                source_ref=source_ref,
                confidence=0.88,
                payload={},
                observed_at=observed_at,
            )
            model_nodes.append(model_node)
            nodes.append(model_node)

        customer_name = first_fact_value(facts, "customer_name") or first_fact_value(facts, "buyer_name")
        customer_node = None
        if case_id and customer_name:
            customer_node = build_graph_node(
                node_type="Customer",
                natural_key=customer_name.lower(),
                title=customer_name,
                source="gdrive",
                source_ref=source_ref,
                confidence=0.76,
                payload={},
                observed_at=observed_at,
            )
            nodes.append(customer_node)

        location_value = (
            first_fact_value(facts, "installation_address")
            or first_fact_value(facts, "investment_address")
            or first_fact_value(facts, "city")
        )
        location_node = None
        if case_id and location_value:
            location_node = build_graph_node(
                node_type="Location",
                natural_key=location_value.lower(),
                title=location_value,
                source="gdrive",
                source_ref=source_ref,
                confidence=0.76,
                payload={},
                observed_at=observed_at,
            )
            nodes.append(location_node)

        return {
            "nodes": nodes,
            "document_node": document_node,
            "kind_node": kind_node,
            "case_node": case_node,
            "manufacturer_node": manufacturer_node,
            "offer_family_node": offer_family_node,
            "model_nodes": model_nodes,
            "customer_node": customer_node,
            "location_node": location_node,
            "case_id": case_id,
        }

"""

GRAPH_EDGES = r"""    def _build_graph_edges(
        self,
        record: dict[str, Any],
        *,
        facts: list[dict[str, Any]],
        node_map: dict[str, Any],
        observed_at: str,
        source_ref: str,
    ) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        document_node = node_map["document_node"]
        kind_node = node_map["kind_node"]
        case_node = node_map["case_node"]
        case_id = node_map["case_id"]

        if case_id and case_node:
            edges.append(
                build_graph_edge(
                    src_node_id=case_node["node_id"],
                    dst_node_id=document_node["node_id"],
                    relation_type="case_has_document",
                    source="gdrive",
                    source_ref=source_ref,
                    confidence=float(record.get("link_confidence") or 0.0),
                    metadata={"document_kind": record.get("document_kind")},
                    observed_at=observed_at,
                )
            )
            relation_type = RELATION_BY_KIND.get(str(record.get("document_kind") or ""))
            if relation_type and kind_node is not None:
                edges.append(
                    build_graph_edge(
                        src_node_id=case_node["node_id"],
                        dst_node_id=kind_node["node_id"],
                        relation_type=relation_type,
                        source="gdrive",
                        source_ref=source_ref,
                        confidence=float(record.get("link_confidence") or 0.0),
                        metadata={},
                        observed_at=observed_at,
                    )
                )

        if node_map["offer_family_node"] and case_id:
            edges.append(
                build_graph_edge(
                    src_node_id=stable_graph_node_id("Case", case_id),
                    dst_node_id=node_map["offer_family_node"]["node_id"],
                    relation_type="case_uses_offer_family",
                    source="gdrive",
                    source_ref=source_ref,
                    confidence=0.8,
                    metadata={},
                    observed_at=observed_at,
                )
            )

        for model_node in node_map["model_nodes"]:
            edges.append(
                build_graph_edge(
                    src_node_id=document_node["node_id"],
                    dst_node_id=model_node["node_id"],
                    relation_type="document_mentions_model",
                    source="gdrive",
                    source_ref=source_ref,
                    confidence=0.86,
                    metadata={"fact_source": "drive_fact"},
                    observed_at=observed_at,
                )
            )
            if node_map["manufacturer_node"] is not None:
                edges.append(
                    build_graph_edge(
                        src_node_id=model_node["node_id"],
                        dst_node_id=node_map["manufacturer_node"]["node_id"],
                        relation_type="model_belongs_to_manufacturer",
                        source="gdrive",
                        source_ref=source_ref,
                        confidence=0.82,
                        metadata={},
                        observed_at=observed_at,
                    )
                )
            if node_map["offer_family_node"] is not None:
                edges.append(
                    build_graph_edge(
                        src_node_id=node_map["offer_family_node"]["node_id"],
                        dst_node_id=model_node["node_id"],
                        relation_type="offer_family_uses_model",
                        source="gdrive",
                        source_ref=source_ref,
                        confidence=0.78,
                        metadata={},
                        observed_at=observed_at,
                    )
                )

        if node_map["customer_node"] and case_id:
            edges.append(
                build_graph_edge(
                    src_node_id=stable_graph_node_id("Case", case_id),
                    dst_node_id=node_map["customer_node"]["node_id"],
                    relation_type="case_has_customer",
                    source="gdrive",
                    source_ref=source_ref,
                    confidence=0.76,
                    metadata={},
                    observed_at=observed_at,
                )
            )

        if node_map["location_node"] and case_id:
            edges.append(
                build_graph_edge(
                    src_node_id=stable_graph_node_id("Case", case_id),
                    dst_node_id=node_map["location_node"]["node_id"],
                    relation_type="case_has_location",
                    source="gdrive",
                    source_ref=source_ref,
                    confidence=0.76,
                    metadata={},
                    observed_at=observed_at,
                )
            )

        return edges

"""

GRAPH_RELATIONSHIP = r"""    def _build_graph_relationship(
        self,
        record: dict[str, Any],
        *,
        node_map: dict[str, Any],
        observed_at: str,
        source_ref: str,
    ) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        kind_node = node_map["kind_node"]
        document_node = node_map["document_node"]
        relation_source_node_id = kind_node["node_id"] if kind_node is not None else document_node["node_id"]
        case_id = node_map["case_id"]

        if str(record.get("document_kind") or "") == "media_asset":
            parent_bundle_key = str((record.get("metadata") or {}).get("parent_drive_item_id") or "")
            if parent_bundle_key:
                bundle_node = build_graph_node(
                    node_type="MediaBundle",
                    natural_key=parent_bundle_key,
                    title=str(record.get("folder_path") or "Media bundle"),
                    source="gdrive",
                    source_ref=source_ref,
                    confidence=0.7,
                    payload={},
                    observed_at=observed_at,
                )
                asset_node = build_graph_node(
                    node_type="MediaAsset",
                    natural_key=str(record.get("document_id") or ""),
                    title=str(record.get("title") or record.get("file_name") or ""),
                    source="gdrive",
                    source_ref=source_ref,
                    confidence=0.75,
                    payload={},
                    observed_at=observed_at,
                )
                edges.append(
                    build_graph_edge(
                        src_node_id=bundle_node["node_id"],
                        dst_node_id=asset_node["node_id"],
                        relation_type="media_bundle_has_asset",
                        source="gdrive",
                        source_ref=source_ref,
                        confidence=0.75,
                        metadata={},
                        observed_at=observed_at,
                    )
                )
                if case_id:
                    edges.append(
                        build_graph_edge(
                            src_node_id=stable_graph_node_id("Case", case_id),
                            dst_node_id=bundle_node["node_id"],
                            relation_type="case_has_media_bundle",
                            source="gdrive",
                            source_ref=source_ref,
                            confidence=float(record.get("link_confidence") or 0.0),
                            metadata={"asset_document_id": record.get("document_id")},
                            observed_at=observed_at,
                        )
                    )

        for model_node in node_map["model_nodes"]:
            doc_kind = str(record.get("document_kind") or "")
            if doc_kind == "price_list":
                edges.append(
                    build_graph_edge(
                        src_node_id=relation_source_node_id,
                        dst_node_id=model_node["node_id"],
                        relation_type="price_list_prices_model",
                        source="gdrive",
                        source_ref=source_ref,
                        confidence=0.84,
                        metadata={},
                        observed_at=observed_at,
                    )
                )
            elif doc_kind == "pricing_workbook":
                edges.append(
                    build_graph_edge(
                        src_node_id=relation_source_node_id,
                        dst_node_id=model_node["node_id"],
                        relation_type="workbook_contains_cost_for_model",
                        source="gdrive",
                        source_ref=source_ref,
                        confidence=0.84,
                        metadata={},
                        observed_at=observed_at,
                    )
                )
            elif doc_kind == "technical_reference":
                edges.append(
                    build_graph_edge(
                        src_node_id=relation_source_node_id,
                        dst_node_id=model_node["node_id"],
                        relation_type="technical_reference_supports_model_family",
                        source="gdrive",
                        source_ref=source_ref,
                        confidence=0.76,
                        metadata={},
                        observed_at=observed_at,
                    )
                )

        return edges

"""

THIN_BUILD_GRAPH = r"""    def _build_graph_upsert(self, record: dict[str, Any], *, facts: list[dict[str, Any]]) -> DriveGraphUpsert:
        observed_at = str((record.get("metadata") or {}).get("modified_time") or datetime.now().astimezone().isoformat())
        source_ref = str(record.get("source_ref") or "")

        node_map = self._build_graph_nodes(record, facts=facts, observed_at=observed_at, source_ref=source_ref)
        edges = self._build_graph_edges(record, facts=facts, node_map=node_map, observed_at=observed_at, source_ref=source_ref)
        relationship_edges = self._build_graph_relationship(record, node_map=node_map, observed_at=observed_at, source_ref=source_ref)
        edges.extend(relationship_edges)

        nodes = node_map["nodes"]
        dedup_nodes = {node["node_id"]: node for node in nodes}
        dedup_edges = {edge["edge_id"]: edge for edge in edges}
        return DriveGraphUpsert(nodes=list(dedup_nodes.values()), edges=list(dedup_edges.values()))

"""

print("Applying refactoring 2/3: _build_graph_upsert")
rep(1043, 1355, GRAPH_NODES + GRAPH_EDGES + GRAPH_RELATIONSHIP + THIN_BUILD_GRAPH)


# ================================================================
# 3. REFACTOR extract_drive_facts (L1453-L1742 = indices 1452-1741)
# ================================================================

FACT_HELPER = r"""def _build_drive_fact_row(
    document_id: str,
    fact_family: str,
    fact_key: str,
    normalized_value: str,
    raw_value: str,
    confidence: float,
    observed_at: str,
    source_ref: str,
    lane: str,
    document_kind: str,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"lane": lane, "document_kind": document_kind}
    if extra_metadata:
        metadata.update(extra_metadata)
    return build_fact(
        document_id=document_id,
        fact_family=fact_family,
        fact_key=fact_key,
        normalized_value=normalized_value,
        raw_value=raw_value,
        confidence=confidence,
        observed_at=observed_at,
        source_ref=source_ref,
        metadata=metadata,
    )


"""

FACT_KEYS = r"""def _extract_drive_fact_keys(
    candidate: DriveIngestCandidate,
    *,
    document_id: str,
    combined_text: str,
    lowered: str,
    observed_at: str,
    source_ref: str,
    lane: str,
    document_kind: str,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []

    probable_case_key = str(candidate.probable_case_key or "").strip()
    if probable_case_key:
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="linkage", fact_key="probable_case_key",
                normalized_value=probable_case_key, raw_value=probable_case_key,
                confidence=0.98, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    for match in ORDER_RE.finditer(combined_text):
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="transaction", fact_key="order_number",
                normalized_value=clean_identifier(match.group(0)), raw_value=match.group(0),
                confidence=0.95, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    for match in INVOICE_RE.finditer(combined_text):
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="transaction", fact_key="invoice_number",
                normalized_value=clean_identifier(match.group(0)), raw_value=match.group(0),
                confidence=0.95, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    for match in DEPOSIT_RE.finditer(combined_text):
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="transaction", fact_key="deposit_invoice_number",
                normalized_value=clean_identifier(match.group(0)), raw_value=match.group(0),
                confidence=0.95, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    for match in MODEL_RE.finditer(combined_text.upper()):
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="technical_reference", fact_key="device_model",
                normalized_value=clean_identifier(match.group(0)), raw_value=match.group(0),
                confidence=0.92, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    manufacturer = infer_manufacturer(combined_text)
    if manufacturer:
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="technical_reference", fact_key="manufacturer",
                normalized_value=manufacturer, raw_value=manufacturer,
                confidence=0.85, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    offer_family = infer_offer_family(combined_text)
    if offer_family:
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="offer_family", fact_key="offer_family",
                normalized_value=offer_family, raw_value=offer_family,
                confidence=0.8, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    customer_name = infer_customer_name(combined_text)
    if customer_name:
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="contract", fact_key="customer_name",
                normalized_value=customer_name, raw_value=customer_name,
                confidence=0.72, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    email_match = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", combined_text, re.IGNORECASE)
    if email_match:
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="contract", fact_key="customer_email",
                normalized_value=email_match.group(0).lower(), raw_value=email_match.group(0),
                confidence=0.88, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    address_match = ADDRESS_RE.search(combined_text)
    if address_match:
        address_value = re.sub(r"\s+", " ", address_match.group(0)).strip()
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="contract", fact_key="installation_address",
                normalized_value=address_value, raw_value=address_value,
                confidence=0.7, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    city_match = re.search(
        r"\b(?:Jaworzno|Sosnowiec|Chorzow|Olkusz|Regulice|Siedlec|Psary|Gleboka|Zubadan|Panasia)\b",
        combined_text, re.IGNORECASE,
    )
    if city_match:
        city_value = city_match.group(0).strip().title()
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="contract", fact_key="city",
                normalized_value=city_value, raw_value=city_value,
                confidence=0.68, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    for match in DATE_RE.finditer(combined_text):
        normalized_date = normalize_date(match.group(1))
        if normalized_date:
            facts.append(
                _build_drive_fact_row(
                    document_id=document_id, fact_family="document", fact_key="document_date",
                    normalized_value=normalized_date, raw_value=match.group(1),
                    confidence=0.7, observed_at=observed_at, source_ref=source_ref,
                    lane=lane, document_kind=document_kind,
                )
            )
            break

    warranty_match = WARRANTY_TERM_RE.search(lowered)
    if warranty_match:
        raw_val = warranty_match.group(0)
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="warranty", fact_key="warranty_term",
                normalized_value=clean_identifier(raw_val), raw_value=raw_val,
                confidence=0.86, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    service_match = SERVICE_FREQ_RE.search(lowered)
    if service_match:
        raw_val = service_match.group(0)
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="warranty", fact_key="service_frequency",
                normalized_value=clean_identifier(raw_val), raw_value=raw_val,
                confidence=0.82, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    serial_match = SERIAL_RE.search(combined_text)
    if serial_match:
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="technical_reference", fact_key="serial_number",
                normalized_value=clean_identifier(serial_match.group(1)), raw_value=serial_match.group(1),
                confidence=0.92, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
            )
        )

    return facts

"""

FACT_VALUES = r"""def _extract_drive_fact_values(
    candidate: DriveIngestCandidate,
    *,
    document_id: str,
    combined_text: str,
    observed_at: str,
    source_ref: str,
    lane: str,
    document_kind: str,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []

    if document_kind in {"price_list", "pricing_workbook"} or lane == "commercial_pricing":
        facts.extend(
            extract_pricing_facts(
                candidate,
                document_id=document_id,
                combined_text=combined_text,
                observed_at=observed_at,
                source_ref=source_ref,
            )
        )

    return facts

"""

THIN_EXTRACT_FACTS = r"""def extract_drive_facts(
    candidate: DriveIngestCandidate,
    *,
    document_id: str,
    text: str,
    observed_at: str,
    source_ref: str,
) -> list[dict[str, Any]]:
    combined_text = "\n".join(part for part in (candidate.title, candidate.folder_path, text) if part)
    lowered = combined_text.lower()
    lane = candidate.lane
    document_kind = candidate.document_kind

    facts: list[dict[str, Any]] = []

    # Key-based regex fact extractions
    facts.extend(
        _extract_drive_fact_keys(
            candidate=candidate,
            document_id=document_id,
            combined_text=combined_text,
            lowered=lowered,
            observed_at=observed_at,
            source_ref=source_ref,
            lane=lane,
            document_kind=document_kind,
        )
    )

    # Build model bundle from individual device_model values
    model_values = [f["normalized_value"] for f in facts if f.get("fact_key") in {"device_model", "device_model_bundle", "model_bundle"}]
    model_values = [v for v in model_values if v]
    unique_models = sorted(set(model_values))
    if unique_models:
        facts.append(
            _build_drive_fact_row(
                document_id=document_id, fact_family="technical_reference", fact_key="device_model_bundle",
                normalized_value=" | ".join(unique_models), raw_value=", ".join(unique_models),
                confidence=0.84, observed_at=observed_at, source_ref=source_ref,
                lane=lane, document_kind=document_kind,
                extra_metadata={"count": len(unique_models)},
            )
        )

    # Value-based extractions (pricing)
    facts.extend(
        _extract_drive_fact_values(
            candidate=candidate,
            document_id=document_id,
            combined_text=combined_text,
            observed_at=observed_at,
            source_ref=source_ref,
            lane=lane,
            document_kind=document_kind,
        )
    )

    return dedupe_facts(facts)


"""

print("Applying refactoring 3/3: extract_drive_facts")
rep(1452, 1741, FACT_HELPER + FACT_KEYS + FACT_VALUES + THIN_EXTRACT_FACTS)


with open(FILEPATH, "w", encoding="utf-8") as f:
    f.writelines(lines)

print(f"\nDone. Wrote {len(lines)} lines.")
