#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

HTML_START = "HTML = r'''"
HTML_END = "'''.replace(\"__TAGGING_DOCS_URL__\""

LIVE_REPO = "https://github.com/lucaperl/paperless-local-ai"
DOCS_BASE = f"{LIVE_REPO}/blob/main"

API_FETCH = '''async function api(path,opts={}){const r=await fetch(path,{headers:{'Content-Type':'application/json'},...opts});const t=await r.text();let data;try{data=JSON.parse(t)}catch{data={error:t}}if(!r.ok)throw new Error(data.error||`${r.status} ${r.statusText}`);return data}'''
API_MOCK = '''async function api(path,opts={}){return window.PLAI_DEMO.api(path,opts)}'''

CSP_META = '''<meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">'''

DEMO_CSS = r'''
.demo-banner{position:sticky;top:0;z-index:30;min-height:44px;padding:8px 18px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:#201909;border-bottom:1px solid #6a5127;color:#f7ddb0}
.demo-banner strong{color:#ffd58b}.demo-banner .demo-copy{color:#d9c39e}.demo-banner .demo-docs{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.demo-banner button{width:auto}
.demo-banner .demo-doc{border:1px solid #6a5127;background:#2b2110;color:#ffd58b;border-radius:7px;padding:4px 8px}.demo-banner .demo-doc:hover{background:#3a2b12}
.demo-banner .demo-reset{margin-left:auto;border:1px solid #6a5127;background:#2b2110;color:#f7ddb0;border-radius:7px;padding:5px 9px}.demo-banner .demo-reset:hover{background:#3a2b12}
.topbar{top:44px}
@media(max-width:760px){.demo-banner{position:static;padding:9px 12px}.demo-banner .demo-reset{margin-left:0}.topbar{top:0}}
'''

DEMO_BANNER = r'''<div class="demo-banner" role="status">
  <strong>Demo mode</strong>
  <span class="demo-copy">Browser-only synthetic Paperless, Ollama and OCR data.</span>
  <span class="demo-docs">Try:
    <button type="button" class="demo-doc" data-demo-document="4711">4711 · History match</button>
    <button type="button" class="demo-doc" data-demo-document="4712">4712 · LLM fallback</button>
    <button type="button" class="demo-doc" data-demo-document="4713">4713 · conservative</button>
  </span>
  <button type="button" class="demo-reset" id="demo-reset">Reset demo</button>
</div>'''


class StaticEvalError(ValueError):
    pass


def static_eval(node: ast.AST, env: dict[str, object]) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise StaticEvalError(node.id)
        return env[node.id]
    if isinstance(node, ast.Dict):
        return {
            static_eval(key, env): static_eval(value, env)
            for key, value in zip(node.keys, node.values, strict=True)
        }
    if isinstance(node, ast.List):
        return [static_eval(item, env) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(static_eval(item, env) for item in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -static_eval(node.operand, env)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return static_eval(node.left, env) + static_eval(node.right, env)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and len(node.args) == 1 and not node.keywords:
        value = static_eval(node.args[0], env)
        if node.func.id == "list":
            return list(value)
        if node.func.id == "tuple":
            return tuple(value)
    raise StaticEvalError(ast.dump(node, include_attributes=False))


def source_constants(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    env: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            env[target.id] = static_eval(node.value, env)
        except StaticEvalError:
            continue
    return env


def js_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def extract_control_center(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    start = text.find(HTML_START)
    if start < 0:
        raise SystemExit(f"Control Center HTML start marker missing in {source}")
    start += len(HTML_START)
    tail = text[start:]
    end = tail.find(HTML_END)
    if end < 0:
        raise SystemExit(f"Control Center HTML end marker missing in {source}")
    html = tail[:end]
    required = [
        "paperless-local-ai Control Center",
        "__TAGGING_DOCS_URL__",
        "__PAPERLESS_SETUP_DOCS_URL__",
        "__APP_VERSION__",
        API_FETCH,
    ]
    missing = [marker for marker in required if marker not in html]
    if missing:
        raise SystemExit(f"Control Center demo build contract changed; missing: {missing}")
    return html


def render_mock_source(repo: Path) -> str:
    mock_path = repo / "demo" / "mock-api.js"
    mock = mock_path.read_text(encoding="utf-8")

    prompt_constants = source_constants(repo / "src" / "core" / "prompt_runtime.py")
    app_constants = source_constants(repo / "src" / "common" / "app_config.py")

    required_prompt = ["DEFAULT_CONFIG", "PROMPT_PRESETS", "PLACEHOLDERS"]
    missing_prompt = [name for name in required_prompt if name not in prompt_constants]
    if missing_prompt:
        raise SystemExit(f"Could not statically read prompt defaults: {missing_prompt}")
    if "DEFAULT_CONFIG" not in app_constants:
        raise SystemExit("Could not statically read App Settings defaults")

    replacements = {
        "__PROMPT_CONFIG_DEFAULT_JSON__": js_json(prompt_constants["DEFAULT_CONFIG"]),
        "__PROMPT_PRESETS_JSON__": js_json(prompt_constants["PROMPT_PRESETS"]),
        "__PLACEHOLDERS_JSON__": js_json(prompt_constants["PLACEHOLDERS"]),
        "__APP_CONFIG_DEFAULT_JSON__": js_json(app_constants["DEFAULT_CONFIG"]),
    }
    for marker, value in replacements.items():
        if marker not in mock:
            raise SystemExit(f"Demo mock marker missing: {marker}")
        mock = mock.replace(marker, value)

    unresolved = [marker for marker in replacements if marker in mock]
    if unresolved:
        raise SystemExit(f"Unresolved demo mock markers: {unresolved}")
    return mock


def build_html(repo: Path) -> str:
    html = extract_control_center(repo / "src" / "core" / "prompt_ui.py")
    version = (repo / "VERSION").read_text(encoding="utf-8").strip() or "dev"

    html = html.replace("__TAGGING_DOCS_URL__", f"{DOCS_BASE}/docs/tagging.md")
    html = html.replace("__PAPERLESS_SETUP_DOCS_URL__", f"{DOCS_BASE}/docs/paperless-setup.md")
    html = html.replace("__APP_VERSION__", f"{version} · demo")

    html = html.replace(
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n' + CSP_META,
        1,
    )
    html = html.replace("</style>", DEMO_CSS + "\n</style>", 1)
    html = html.replace(
        '<main class="main">\n<header class="topbar">',
        '<main class="main">\n' + DEMO_BANNER + '\n<header class="topbar">',
        1,
    )

    if API_FETCH not in html:
        raise SystemExit("Production API fetch function changed; refusing to build a stale demo shim")
    html = html.replace(API_FETCH, API_MOCK, 1)

    mock = render_mock_source(repo)
    if "<script>" not in html:
        raise SystemExit("Control Center script marker missing")
    html = html.replace("<script>", "<script>\n" + mock + "\n</script>\n<script>", 1)

    if "fetch(path" in html:
        raise SystemExit("Demo output still contains the production API fetch implementation")
    if "connect-src 'none'" not in html:
        raise SystemExit("Demo output is missing the network-blocking CSP")
    if 'data-demo-document="4711"' not in html:
        raise SystemExit("Demo banner was not injected")
    return html


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static browser-only Control Center demo.")
    parser.add_argument("--output", default="_site/demo", help="Output directory (default: _site/demo)")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    output = Path(args.output)
    if not output.is_absolute():
        output = repo / output
    output.mkdir(parents=True, exist_ok=True)

    html = build_html(repo)
    (output / "index.html").write_text(html, encoding="utf-8", newline="\n")
    print(f"Built Control Center demo: {output / 'index.html'}")


if __name__ == "__main__":
    main()
