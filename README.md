# Observatory Formula Checker
    python server.py          # UI + API at http://localhost:8000
    python evaluator.py "-(a + b) * 2 + 30 / 5" -v a=10 -v b=5   # CLI (no args = interactive)
    python test_evaluator.py  # tests
Python 3.8+, standard library only. No eval(): tokenizer, shunting-yard parser, tree builder and evaluator are hand-written.