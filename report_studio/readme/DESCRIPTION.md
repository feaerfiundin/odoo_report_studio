Visual designer for QWeb/PDF reports, built with blocks and with a
permanent version history.

Reports are designed in an editor with three panels: the toolbox on the
left, the page in the center (rendered with the data of a real record, in
the company document layout) and the properties of the selected block on
the right.

Available blocks:

- **Content**: Text, Field (with an optional label) and Table (a one2many or
  many2many field, with column widths in percent).
- **Layout**: Section, Columns (2 to 4, with an optional vertical line),
  Condition, Separator, Spacer and Page Break.

Every block can set its font (size, bold, italic, underline), text
alignment and inner margins where it makes sense. Sections can have a label
bar and borders; tables have a style popup with header, row (also
alternate) and column backgrounds, border schemes, column borders and row
heights. Fields are chosen like in Odoo many2one fields: a few suggestions
and "Search More..." with a searchable list, relations included. Free Python expressions
are never accepted: conditions only compare validated field paths with
scalar values.

Saving creates a new version (the printed one) or only a draft of the work
in progress. The Versions popup shows every version with its editable
comment: a version can be made the active one again, restored as a new
version, copied into a new report or deleted (never the active one).

Reusable blocks: any block (e.g. a section with the data of a contact) can
be saved with "Save as Block" and inserted in other reports from the
"Custom Content" group of the toolbox. A block saved on a linked model
(e.g. res.partner) adapts to each document through the linking field
(customer, delivery address...); the insertion is an independent copy. Native Odoo documents can be copied
into an editable free QWeb report (Administrators only).

Texts, field labels and table headers can be translated, and a report can
be printed in the language of the customer, like the native Odoo documents.
