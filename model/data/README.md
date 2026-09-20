# Classification bootstrap dataset

These 60 training emails and 15 validation emails were authored as synthetic examples during development, with labels assigned by the coding assistant. They are **not official ground truth or independently human-reviewed labels**. The examples reflect the supplied business requirements and the participant-email examples inspected during development; they are not a blind benchmark.

Each line is JSON with `id`, `group`, `category`, `subject`, `body`. Five categories have equal representation: 12 training and 3 validation examples each. Neither email IDs nor filenames, attachment contents or senders are model features. The model uses only the current subject and body.

Validation examples were written separately and are never passed to `fit`. Training refuses overlapping IDs, groups or exact normalized text across splits. Similar paraphrases can still exist across groups: the split guard does not establish real-world independence. A small same-author synthetic validation set is only a development check, not evidence of deployment accuracy.

For real evaluation, manually review and label a separate sample of participant emails, group related threads/templates together, and keep those groups out of training. Ambiguous requests (for example, asking someone to send a draft BL without an SI) need an agreed labelling policy. Do not silently label them from attachments or filenames. The classifier's confidence and margin thresholds are provisional, not calibrated on an independent real-data set.

Current labels:

- `BL_COMPARISON`: asks to check a draft BL against an SI, including incomplete attachment cases.
- `SI_REQUEST`: asks to create/submit new shipping instructions, or supplies instructions to prepare a first draft.
- `INVOICE_QUERY`: asks about billing, invoice amounts, charges or payment.
- `GENERAL`: operational updates, acknowledgements and other mail without those requests.
- `SPAM`: unsolicited promotion, scams or credential-harvesting messages.

Custom training data must use the same schema. The training command currently labels artifact provenance as `synthetic_authored_bootstrap`; update that provenance before using it for a different data source. No scoring answer file is read by this workflow.
