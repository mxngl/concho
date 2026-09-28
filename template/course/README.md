# course/

The **course workbooks** go here, in your team's **private** repository only:

- the course STV workbook (e.g. `CEE_222_STV_V12.xlsx`): **required for STV**. The pipeline
  uses the one `.xlsx` in this folder whose file name contains `STV`. Without it, STV is
  skipped (with a warning) and only TVD runs.

The workbooks are course material: they come from the course Drive and **must never be in a
public repository**. That is why the public Concho template ships this folder empty, with a
`.gitignore` that keeps `*.xlsx` out. **Delete `course/.gitignore` in your private team repo**,
then add the workbook and push.

> **Pending the course lead's answer (decision D5):** whether teams may keep the course
> workbooks in their (private) team repositories. Until then this is the working assumption.
> See [`docs/decisions.md`](https://github.com/mxngl/concho/blob/main/docs/decisions.md).

The pipeline refuses to run when the repository is public and this folder holds a workbook.
