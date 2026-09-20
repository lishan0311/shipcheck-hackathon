# Validation evidence

ShipCheck separates the statistical email classifier from the complete
business pipeline. A model probability is not presented as accuracy.

## Results

| Evaluation | Model-only accuracy | Rules + model classification | Field F1 | End-to-end | Review precision / recall | Final scorer |
|---|---:|---:|---:|---:|---:|---:|
| Supplied 520-email dataset | 72.69% | 100% (520/520) | 100% | 100% (46/46) | 100% / 100% | 1.0000 |
| Independent seed-73 dataset | 70.38% | 100% (520/520) | 100% | 100% (52/52) | 100% / 100% | 1.0000 |

The second dataset was generated with a different deterministic seed after the
pipeline fixes. It contains 244 attachments across TXT, PDF, DOCX and XLSX,
52 injected defects, and 20 reliability cases covering wrong document type,
missing attachment, unreadable input and missing required values.

These results demonstrate repeatable performance against the organizer's
synthetic generator. They do not establish 100% accuracy on unrestricted real
Gmail traffic. Real-world accuracy requires a frozen, human-labelled sample of
new messages from the deployment environment.

## Reproduce the supplied-dataset result

```powershell
.venv\Scripts\python.exe scripts\export_submission.py --output runtime\submission-current.json
.venv\Scripts\python.exe scripts\evaluate_supplied_dataset.py
```

Detailed output: `runtime/evaluation-current.json`.

## Reproduce the independent-seed result

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-evaluation.txt
.venv\Scripts\python.exe sdoc-hackathon-docker\data_v2\generate.py --seed 73 --n 500 --out runtime\holdout-seed-73
.venv\Scripts\python.exe scripts\evaluate_supplied_dataset.py --dataset runtime\holdout-seed-73 --run-pipeline --output runtime\evaluation-holdout-seed-73.json
```

## Production measurement protocol

1. Randomly sample new Gmail messages, including examples from every predicted
   category and every review reason.
2. Have a reviewer label the category and, for comparison requests, the seven
   expected field outcomes without seeing the prediction.
3. Freeze that set before changing the model or rules.
4. Report category macro-F1, field-level F1, end-to-end exact match, review
   precision/recall, processing failures and latency.
5. Add confirmed errors to a separate training set and keep messages from the
   same sender/template in one split to reduce leakage.

The supplied answer key and generated holdout labels are evaluation data only;
the runtime pipeline does not read them.
