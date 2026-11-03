#!/usr/bin/env python3
"""
Haiku 5.5 hot-path measurement harness for the paper-digitizer project.

Runs the per-page "understand this page" call across a matrix of settings and
records, per request: TTFT (first text_delta), time-to-doc_type (first time the
streamed JSON contains a closed "doc_type" value), end-to-end time, usage
(input/cache/output tokens; output_tokens INCLUDES thinking tokens), stop_reason,
stop_details.category, parsed-JSON validity, and the response model/inference_geo.

Status: written 2026-11-03 in a sandbox without an API key; not yet executed against the API.
Expect to fix small things on first run. Pricing constants are Haiku 5.5 list prices (Nov 2026).

Usage:
  pip install "anthropic>=1.0" pillow
  export ANTHROPIC_API_KEY=sk-ant-...
  python3 haiku_hot_path_bench.py --pages ./pages --ocr ./ocr --out results.jsonl \
      --arms image,both,text --sizes 1100,1568,2576 --thinking disabled,adaptive-low \
      --geo us --repeats 1

`./pages/*.jpg` are the handheld captures (full resolution; the script resizes).
`./ocr/<same-stem>.txt` are the on-device Vision OCR transcripts (optional for
the image-only arm). Ground truth for accuracy scoring goes in `./truth/<stem>.json`
(optional); if present, doc_type / document_date / amounts.total are compared.

Everything is written as JSON lines so p50/p95 can be computed afterwards with
`python3 haiku_hot_path_bench.py --summarize results.jsonl`.
"""
import argparse, base64, io, json, math, os, statistics, sys, time
from pathlib import Path

MODEL = "claude-haiku-5-5"

SCHEMA = {
  "type": "object", "additionalProperties": False,
  "required": ["doc_type", "doc_subtype", "language", "sender", "document_date",
               "due_date", "tax_year", "amounts", "identifiers", "tags", "title",
               "summary", "page_role", "confidence", "needs_review", "review_reason"],
  "properties": {
    "doc_type": {"type": "string", "enum": [
      "invoice","bill","receipt","bank_statement","credit_card_statement","tax_form",
      "tax_notice","payslip","insurance_policy","insurance_claim","medical_record",
      "medical_bill","prescription","legal_contract","legal_notice","court_document",
      "government_letter","utility","mortgage_loan","investment_statement",
      "pension_retirement","vehicle","property","education","employment","travel",
      "subscription_membership","personal_letter","marketing","warranty_manual",
      "id_document","certificate","other"]},
    "doc_subtype": {"type": ["string","null"]},
    "language": {"type": "string"},
    "sender": {"type": ["string","null"]},
    "document_date": {"type": ["string","null"], "format": "date"},
    "due_date": {"type": ["string","null"], "format": "date"},
    "tax_year": {"type": ["integer","null"]},
    "amounts": {"type": "array", "items": {"type": "object", "additionalProperties": False,
       "required": ["label","value","currency"],
       "properties": {"label": {"type": "string", "enum": ["total","amount_due","subtotal","tax","paid","balance","other"]},
                      "value": {"type": "number"}, "currency": {"type": "string"}}}},
    "identifiers": {"type": "array", "items": {"type": "object", "additionalProperties": False,
       "required": ["kind","value"],
       "properties": {"kind": {"type": "string", "enum": ["account_number","invoice_number","policy_number","claim_number","case_number","reference","member_id","order_number","other"]},
                      "value": {"type": "string"}}}},
    "tags": {"type": "array", "items": {"type": "string"}},
    "title": {"type": "string"},
    "summary": {"type": "string"},
    "page_role": {"type": "string", "enum": ["single","first","continuation","last","blank","envelope"]},
    "confidence": {"type": "number"},
    "needs_review": {"type": "boolean"},
    "review_reason": {"type": ["string","null"]}
  }
}

SYSTEM = (
  "You classify and extract metadata from one photographed page of personal paper mail. "
  "Return only the JSON record. Use the OCR transcript (if given) for exact strings; use the image "
  "for layout, logos, checkboxes, stamps and handwriting. Dates are ISO-8601. Currency is ISO-4217. "
  "tags: 3-8 lowercase words. title: filename-safe, <= 80 chars, starting with the document date. "
  "summary: two sentences, no reasoning. If the page is unreadable set needs_review=true and say why. "
  # pad the system prompt so it clears the 512-token cache minimum in real use; replace with the real taxonomy
  + ("Taxonomy guidance: " + " ".join(f"{t}: typical sender and layout cues." for t in SCHEMA["properties"]["doc_type"]["enum"]))
)

def visual_tokens(w, h): return math.ceil(w/28) * math.ceil(h/28)

def resized_size(w, h, max_edge=2576, max_tokens=4784):
    """Exact Anthropic resize rule (high-res tier defaults)."""
    def fits(a, b): return math.ceil(a/28)*28 <= max_edge and math.ceil(b/28)*28 <= max_edge and visual_tokens(a, b) <= max_tokens
    if fits(w, h): return (w, h)
    if h > w:
        rh, rw = resized_size(h, w, max_edge, max_tokens); return (rw, rh)
    ar = w/h; lo, hi = 1, w
    while lo + 1 < hi:
        mid = (lo+hi)//2
        if fits(mid, max(round(mid/ar), 1)): lo = mid
        else: hi = mid
    return (lo, max(round(lo/ar), 1))

def load_image_b64(path, long_edge, quality=85):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    w, h = im.size
    scale = long_edge / max(w, h)
    if scale < 1: im = im.resize((round(w*scale), round(h*scale)), Image.LANCZOS)
    w2, h2 = resized_size(*im.size)
    if (w2, h2) != im.size: im = im.resize((w2, h2), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=quality, optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode(), im.size, len(buf.getvalue())

def build_request(arm, img_b64, ocr_text, thinking_mode, geo):
    content = []
    if arm in ("image", "both") and img_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64},
                        "transformations": {"oversized_image": "error"}})
    if arm in ("text", "both") and ocr_text:
        content.append({"type": "text", "text": "OCR transcript (Apple Vision, on-device):\n" + ocr_text})
    content.append({"type": "text", "text": "Extract the record for this page."})
    req = dict(model=MODEL, max_tokens=1500,
               system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
               messages=[{"role": "user", "content": content}],
               output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}})
    if thinking_mode == "disabled": req["thinking"] = {"type": "disabled"}
    else: req["thinking"] = {"type": "adaptive"}          # effort low
    if geo: req["inference_geo"] = geo
    return req

def run_one(client, req):
    t0 = time.perf_counter(); ttft = None; t_doc_type = None; text = ""; usage = None
    stop_reason = None; stop_details = None; model = None; err = None
    try:
        with client.messages.stream(**req) as stream:
            for ev in stream:
                if ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                    if ttft is None: ttft = time.perf_counter() - t0
                    text += ev.delta.text
                    if t_doc_type is None and '"doc_type"' in text:
                        after = text.split('"doc_type"', 1)[1]
                        if after.count('"') >= 2: t_doc_type = time.perf_counter() - t0
                elif ev.type == "message_start":
                    model = ev.message.model
            final = stream.get_final_message()
            usage = final.usage.model_dump(); stop_reason = final.stop_reason
            stop_details = final.stop_details.model_dump() if final.stop_details else None
    except Exception as e:  # noqa
        err = f"{type(e).__name__}: {e}"
    e2e = time.perf_counter() - t0
    parsed = None
    try: parsed = json.loads(text)
    except Exception: pass
    return dict(ttft_s=ttft, t_doc_type_s=t_doc_type, e2e_s=e2e, usage=usage, stop_reason=stop_reason,
                stop_details=stop_details, model=model, json_ok=parsed is not None, parsed=parsed, error=err,
                raw_len=len(text))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages"); ap.add_argument("--ocr"); ap.add_argument("--truth")
    ap.add_argument("--out", default="results.jsonl")
    ap.add_argument("--arms", default="image,both,text")
    ap.add_argument("--sizes", default="1100,1568,2576")
    ap.add_argument("--thinking", default="disabled,adaptive-low")
    ap.add_argument("--geo", default="us")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--count-tokens-only", action="store_true", help="one count_tokens call per size to confirm the vision tier")
    ap.add_argument("--summarize")
    a = ap.parse_args()
    if a.summarize: return summarize(a.summarize)
    import anthropic
    client = anthropic.Anthropic(max_retries=0, timeout=60.0)   # no SDK retries: we want raw 429/529 visibility
    pages = sorted(Path(a.pages).glob("*.jp*g"))[: a.limit]
    sizes = [int(s) for s in a.sizes.split(",")]
    if a.count_tokens_only:
        p = pages[0]
        for L in sizes:
            b64, size, nbytes = load_image_b64(p, L)
            req = build_request("image", b64, None, "disabled", None)
            c = client.messages.count_tokens(model=MODEL, system=req["system"], messages=req["messages"])
            print(f"long_edge={L} sent={size} bytes={nbytes} expected_visual_tokens={visual_tokens(*size)} count_tokens.input_tokens={c.input_tokens}")
        return
    with open(a.out, "a") as out:
        for p in pages:
            ocr = (Path(a.ocr)/f"{p.stem}.txt").read_text() if a.ocr and (Path(a.ocr)/f"{p.stem}.txt").exists() else None
            truth = json.loads((Path(a.truth)/f"{p.stem}.json").read_text()) if a.truth and (Path(a.truth)/f"{p.stem}.json").exists() else None
            for L in sizes:
                b64, size, nbytes = load_image_b64(p, L)
                for arm in a.arms.split(","):
                    for th in a.thinking.split(","):
                        for r in range(a.repeats):
                            req = build_request(arm, b64 if arm != "text" else None, ocr, th, a.geo or None)
                            res = run_one(client, req)
                            res.update(page=p.name, long_edge=L, sent_size=size, jpeg_bytes=nbytes,
                                       visual_tokens=visual_tokens(*size) if arm != "text" else 0,
                                       arm=arm, thinking=th, repeat=r, ts=time.time())
                            if truth and res["parsed"]:
                                res["acc_doc_type"] = res["parsed"].get("doc_type") == truth.get("doc_type")
                                res["acc_date"] = res["parsed"].get("document_date") == truth.get("document_date")
                            out.write(json.dumps(res) + "\n"); out.flush()
                            print(f"{p.name} L={L} {arm} {th}: ttft={res['ttft_s']} doc_type@{res['t_doc_type_s']} e2e={res['e2e_s']:.2f} stop={res['stop_reason']} out_tok={(res['usage'] or {}).get('output_tokens')} err={res['error']}")

def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs: return None
    k = (len(xs)-1)*q; f = math.floor(k); c = min(f+1, len(xs)-1)
    return xs[f] + (xs[c]-xs[f])*(k-f)

def summarize(path):
    rows = [json.loads(l) for l in open(path)]
    keys = sorted({(r["arm"], r["long_edge"], r["thinking"]) for r in rows})
    print("arm | long_edge | thinking | n | TTFT p50/p95 | doc_type p50/p95 | e2e p50/p95 | out_tok p50/p95 | uncached_in p50 | refusal% | json_ok% | err% | $/page@list")
    for k in keys:
        rs = [r for r in rows if (r["arm"], r["long_edge"], r["thinking"]) == k]
        u = [r["usage"] for r in rs if r["usage"]]
        out_tok = [x["output_tokens"] for x in u]
        inp = [x["input_tokens"] + x.get("cache_creation_input_tokens", 0) for x in u]
        cache = [x.get("cache_read_input_tokens", 0) for x in u]
        cost = [ (x["input_tokens"]*0.10 + x.get("cache_creation_input_tokens",0)*0.125 + x.get("cache_read_input_tokens",0)*0.01 + x["output_tokens"]*0.50)/1e6 for x in u]
        ref = sum(1 for r in rs if r["stop_reason"] == "refusal")/len(rs)*100
        jok = sum(1 for r in rs if r["json_ok"])/len(rs)*100
        err = sum(1 for r in rs if r["error"])/len(rs)*100
        def f2(x): return "n/a" if x is None else f"{x:.2f}"
        ttft = [r["ttft_s"] for r in rs]; tdt = [r["t_doc_type_s"] for r in rs]; e2e = [r["e2e_s"] for r in rs]
        med_cost = f"${statistics.median(cost):.6f}" if cost else "n/a"
        print(f"{k[0]} | {k[1]} | {k[2]} | {len(rs)} | {f2(pct(ttft,.5))}/{f2(pct(ttft,.95))} | "
              f"{f2(pct(tdt,.5))}/{f2(pct(tdt,.95))} | "
              f"{f2(pct(e2e,.5))}/{f2(pct(e2e,.95))} | {pct(out_tok,.5)}/{pct(out_tok,.95)} | {pct(inp,.5)} (cache {pct(cache,.5)}) | {ref:.1f} | {jok:.1f} | {err:.1f} | {med_cost}")

if __name__ == "__main__":
    main()
