"""Backend: stdlib HTTP server with SQLite history, assistant and PDF reports. Run: python server.py [port]"""
import json, os, re, sqlite3, sys, time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from evaluator import evaluate
from agent import answer, diagnose
from pdf_report import build_pdf

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "history.db")
KEEP = 500


def q(sql, args=(), one=False, all=False):
    with closing(sqlite3.connect(DB)) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(sql, args)
        c.commit()
        return cur.fetchone() if one else cur.fetchall() if all else cur.lastrowid


q("create table if not exists scans(id integer primary key autoincrement, ts integer, expression text, ok integer,"
  " result text, error_kind text, error_message text, variables text, record text)")


def load(rid):
    row = q("select * from scans where id=?", (rid,), one=True)
    if not row:
        return None
    rec = json.loads(row["record"])
    rec.update(id=row["id"], ts=row["ts"], variables=json.loads(row["variables"]))
    return rec


def save(rec, variables):
    if rec["error"]:
        rec["suggestion"] = diagnose(rec)
    ts = int(time.time())
    e = rec["error"] or {}
    rid = q("insert into scans(ts,expression,ok,result,error_kind,error_message,variables,record) values(?,?,?,?,?,?,?,?)",
            (ts, rec["expression"], int(rec["ok"]), rec["result"], e.get("kind"), e.get("message"),
             json.dumps(variables), json.dumps(rec)))
    q("delete from scans where id not in (select id from scans order by id desc limit ?)", (KEEP,))
    rec.update(id=rid, ts=ts, variables=variables)
    return rec


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "pdf" not in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > 200_000:
            raise ValueError("too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html")
        if self.path == "/api/history":
            rows = q("select id,ts,expression,ok,result,error_kind from scans order by id desc limit 200", all=True)
            return self._send(200, [dict(r) for r in rows])
        m = re.fullmatch(r"/api/history/(\d+)", self.path)
        if m:
            rec = load(int(m.group(1)))
            return self._send(200 if rec else 404, rec or {"error": "not found"})
        self._send(404, {"error": "not found"})

    def do_DELETE(self):
        if self.path == "/api/history":
            q("delete from scans")
            return self._send(200, {"ok": True})
        m = re.fullmatch(r"/api/history/(\d+)", self.path)
        if m:
            q("delete from scans where id=?", (int(m.group(1)),))
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            p = self._body()
            if self.path == "/api/evaluate":
                expr, vs = p.get("expression", ""), p.get("variables", {})
                if not isinstance(expr, str) or not isinstance(vs, dict):
                    raise ValueError
                return self._send(200, save(evaluate(expr, vs), vs))
            if self.path == "/api/agent":
                rec = load(int(p.get("id", 0)))
                if not rec or not isinstance(p.get("question"), str):
                    raise ValueError
                text, src = answer(p["question"][:500], rec, p.get("history", []))
                return self._send(200, {"answer": text, "source": src})
            if self.path == "/api/report":
                ids = p.get("ids")
                if ids is not None:
                    if not isinstance(ids, list):
                        raise ValueError
                    recs = [load(int(i)) for i in ids[:50]]
                else:
                    recs = [load(r["id"]) for r in q("select id from scans order by id desc limit 50", all=True)]
                recs = [r for r in recs if r]
                if not recs:
                    return self._send(404, {"error": "nothing to report"})
                name = f"observatory-report-{recs[0]['id']}.pdf" if len(recs) == 1 else "observatory-history.pdf"
                return self._send(200, build_pdf(recs), "application/pdf",
                                  {"Content-Disposition": f'attachment; filename="{name}"'})
        except (ValueError, TypeError, KeyError):
            return self._send(400, {"error": "bad request"})
        self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"Observatory evaluator running at http://localhost:{port}")
    ThreadingHTTPServer(("", port), Handler).serve_forever()