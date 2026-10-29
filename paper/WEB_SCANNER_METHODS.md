# Web scanner module for the research paper

This note describes the implementation inspected on 13 October 2026 at commit `b41f7ef`. The module collects search-result snippets through the Serper API. It does not download or parse the linked webpages, and its collected snippets are not currently included in the claim-generation prompt. The manuscript should distinguish this implemented collection step from a future integration of web evidence into synthesis.

## Suggested Methods subsection

### Optional web discovery

The application includes an optional Web Scanner implemented by `EvidenceScannerAgent`. After Patient-Context Extraction, it constructs a search query from the extracted symptoms and known conditions, using normalized names when available and the extracted text otherwise. The terms are placed within the query pattern "clinical guidelines [terms] treatment diagnosis". The scanner submits this query to the Serper search API, requesting three results with a configured request timeout of 10 seconds.

For each organic search result returned by the API, the module records the title, snippet and URL, together with a source label. It does not retrieve the linked page, extract its full text, or verify its publisher, publication date or clinical applicability. The scanner is therefore a search-based discovery component rather than a full-text web scraper. If its API key is absent, or neither symptoms nor known conditions are available, it returns an empty result list. Request failures are logged and do not supply web evidence.

The Retrieval Orchestrator stores the collected records separately as `web_search_results`. In the current implementation, Evidence Ranking and Claim Generation does not consume these records. Web snippets are also ineligible for pinned-source claim citations. Web discovery was disabled in the reported LLM-only, text-RAG and graph-plus-text ablations; the reported outcomes consequently do not establish a benefit from this module.

## Short wording for the architecture section or abstract

> An optional Web Scanner collects search-result snippets as discovery leads. These records are stored separately, are not currently supplied to claim generation, and are not eligible as pinned-source claim citations. Web discovery was disabled during the reported ablations.

## Implementation details and evidence

| Item | Implemented behaviour | Code evidence |
| --- | --- | --- |
| Entry point | `EvidenceScannerAgent.search(context)` receives an extracted `PatientContext`. | [Scanner](../backend/services/evidence_scanner.py) |
| Enablement | The method returns an empty list if `SERPER_API_KEY` is absent, or both symptoms and known conditions are empty. | [Scanner](../backend/services/evidence_scanner.py), [configuration](../backend/config.py) |
| Query terms | Symptom names precede known-condition names. Each term uses `normalized_name` when available, otherwise `text`. Medication terms are not explicitly added by this method. | [Scanner](../backend/services/evidence_scanner.py) |
| Request | An HTTP POST sends the query to `https://google.serper.dev/search`, with `num: 3`, an `X-API-KEY` header and `timeout=10`. | [Scanner](../backend/services/evidence_scanner.py) |
| Returned fields | The method reads the response's `organic` entries and retains `title`, `snippet`, `source` and `url`. The source label is `Serper Web Search`. | [Scanner](../backend/services/evidence_scanner.py) |
| Result count | Three results are requested. The loop processes all organic entries returned; it does not independently truncate the response to three entries. | [Scanner](../backend/services/evidence_scanner.py) |
| Failure handling | HTTP error statuses and other caught `requests.exceptions.RequestException` failures are logged. The method returns its result list; this does not guarantee recovery from every malformed response or programming error. | [Scanner](../backend/services/evidence_scanner.py) |
| Execution order | In the normal application, the orchestrator calls graph retrieval, textbook retrieval, authoritative retrieval, DrugCentral lookup and then web discovery sequentially. | [Orchestrator](../backend/services/orchestrator.py) |
| Storage | Search records are placed in `OrchestratorResult.web_search_results`. | [Retrieval schema](../backend/schemas/retrieval.py), [orchestrator](../backend/services/orchestrator.py) |
| Ranking | The ranker processes graph candidates, textbook passages and DrugCentral associations. It does not process `web_search_results`. | [Evidence ranker](../backend/agents/evidence_ranker.py) |
| Claim generation | The fusion prompt includes selected ranked candidate evidence and pinned `source_passages`. It does not insert the collected web snippets. | [Clinical fusion](../backend/agents/fusion.py) |
| Citation gate | Only permitted pinned guideline and drug-label passages can enter claim citation-identity checks. Search URLs and snippets are not pinned `SourcePassage` records. | [Claim normalization](../backend/services/claim_synthesis.py), [claim verifier](../backend/services/claim_verifier.py) |
| Evaluation | `RetrievalAblation` supplies no web results in `llm_only`, `text_rag` or `graph_text` mode. | [Evaluation runner](../evaluation/run.py), [evaluation documentation](../evaluation/README.md) |

## Important distinction in the fusion prompt

The fusion prompt contains an instruction mentioning graph, textbook, DrugCentral and web results as candidate signals. However, naming web evidence in an instruction does not provide the model with the collected snippets. The prompt builder currently reads the ranked candidate evidence and authoritative passages, while the ranker does not convert web records into candidate evidence. The manuscript must describe this actual data flow rather than infer integration from the prompt wording alone.

## Wording to replace in a manuscript

| Avoid | Use instead |
| --- | --- |
| "The Web Scanner provides the latest information from trusted medical sources." | "The optional Web Scanner collects search-result snippets; source authority and freshness are not verified by this module." |
| "The scraper extracts full-text evidence from PubMed, WHO, FDA and NICE." | "The scanner requests Serper search results and records titles, snippets and URLs. It does not scrape the linked pages or restrict results to a predefined publisher list." |
| "Web evidence is fused with graph and textbook evidence to improve the final answer." | "Collected web results are stored separately but are not currently inserted into the fusion prompt." |
| "Web references are verified clinical citations." | "Web snippets are discovery leads and cannot become pinned-source claim citations." |
| "Parallel web retrieval reduces response time." | "The current orchestrator invokes web discovery sequentially after the other retrieval steps; no concurrent execution or measured latency reduction is established." |
| "The experiments demonstrate the benefit of web intelligence." | "Web discovery was disabled in the reported retrieval ablations, so its effect was not measured." |

## Reproducibility and data handling

The query contains extracted symptom and condition terms, which are sent to Serper when the scanner is enabled. The module also prints the constructed query to application logs. It does not explicitly add the entire raw case text to the search query, but extracted terms should still be considered when documenting data handling.

The current implementation does not archive the response with a timestamp and content hash, pin the linked pages, apply a publisher allowlist, check document versions, or define source-relevance labels. Search results can change between requests. There is no separate evaluation of scanner relevance, freshness, synthesis benefit or citation support.

For reproducing the reported ablations, keep the scanner disabled as in the evaluation runner. Enabling it in the normal application changes the request path and may add external-service latency, but it does not currently add web snippets to the model's synthesis context.

## Future work that must be labelled as proposed

A future integration could retrieve selected linked documents, preserve publisher and version information, assess relevance and patient applicability, and pass eligible evidence to synthesis under an explicit evidence contract. Any proposed incorporation into the pinned-source channel would require the same source-ingestion and independent citation checks used for the existing corpus. A controlled comparison with and without web evidence would be needed before reporting a retrieval or answer-quality benefit. These functions are not implemented by the current scanner.

## Diagram guidance

If the paper includes the optional Web Scanner, label its output "Search snippets stored separately". Do not draw a solid data arrow from it to Claim Generation unless that integration is implemented. A proposed connection may be shown as dashed only when the legend explicitly identifies it as future work. Keep Web Scanner separate from Pinned-Source Retrieval, whose guideline and label passages come from versioned local snapshots.
