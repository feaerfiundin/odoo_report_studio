=============
Report Studio
=============

..
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
   !! This file is generated from the readme/ fragments !!
   !! with the structure of oca-gen-addon-readme.      !!
   !! Changes here may be overwritten: edit readme/.    !!
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
    :target: https://odoo-community.org/page/development-status
    :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
    :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
    :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/github-feaerfiundin%2Fodoo__report__studio-lightgray.png?logo=github
    :target: https://github.com/feaerfiundin/odoo_report_studio/tree/18.0/report_studio
    :alt: feaerfiundin/odoo_report_studio

|badge1| |badge2| |badge3|

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
alignment and inner margins where it makes sense. Free Python expressions
are never accepted: conditions only compare validated field paths with
scalar values.

Every save creates a new immutable version: earlier versions can be
restored or copied into a new report. Native Odoo documents can be copied
into an editable free QWeb report (Administrators only).

Texts, field labels and table headers can be translated, and a report can
be printed in the language of the customer, like the native Odoo documents.

.. IMPORTANT::
   This is an alpha version, the data model and design can change at any time without warning.
   Only for development or testing purpose, do not use in production.

**Table of contents**

.. contents::
   :local:

Configuration
=============

Give users a Report Studio role from the **Report Studio** tab of the user
form (Settings → Users):

- **User**: prints the reports, no access to the designer.
- **Viewer**: sees the designer, the history and the preview, read only.
- **Editor**: creates reports, saves and restores versions, manages the
  Print menu entries.
- **Administrator**: also edits free QWeb and changes the Report Studio roles
  of the other users.

Languages: activate them in Settings → Languages. The editor offers every
active language; the main one is the default language of contacts.

Usage
=====

1. Open **Report Studio → Saved Layouts** and press **New**.
2. Enter the name, choose the model (e.g. ``sale.order``) or a starting
   document, and press **Open Visual Editor**.
3. Add blocks from the toolbox: a block goes inside the selected Section,
   Column or Condition, or after the selected block. Click a block in the
   page to edit its properties.
4. Press **Preview** for the PDF, **Save** to create a new version.
5. To translate the texts, choose a language in the language menu of the
   top bar and write the texts in that language; empty texts are printed in
   the main language. Click an empty spot of the page and enable **Print in
   the customer language** to print in the language of the contact.

To print from the business documents (e.g. from the customer invoice), open
**Report Studio → Reports**, open the report and press **Add to Print
Menu**. The report is then listed in the Print menu of its model. Paper
format, printed file name and attachment are set on the same page.

Known issues / Roadmap
======================

- Semantic blocks (company header, addresses, totals).
- Report templates ("Template", "Save as Template"), test print and help,
  shown as "coming soon" in the editor.
- Drag and drop of blocks (today they are moved with the arrows).

Bug Tracker
===========

Bugs are tracked on `GitHub Issues <https://github.com/feaerfiundin/odoo_report_studio/issues>`_.
In case of trouble, please check there if your issue has already been reported.

Credits
=======

Authors
-------

- feaerfiundin

Contributors
------------

- feaerfiundin

Maintainers
-----------

This module is maintained by feaerfiundin.

This module is part of the `feaerfiundin/odoo_report_studio <https://github.com/feaerfiundin/odoo_report_studio/tree/18.0/report_studio>`_ project on GitHub.

You are welcome to contribute.
