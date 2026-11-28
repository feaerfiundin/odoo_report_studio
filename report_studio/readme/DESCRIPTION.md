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

Every save creates a new immutable version: earlier versions can be
restored or copied into a new report. Native Odoo documents can be copied
into an editable free QWeb report (Administrators only).

Texts, field labels and table headers can be translated, and a report can
be printed in the language of the customer, like the native Odoo documents.
