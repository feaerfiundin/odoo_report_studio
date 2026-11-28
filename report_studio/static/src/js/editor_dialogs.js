/** @odoo-module **/
// Copyright 2026 feaerfiundin
// License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";
import { formatDateTime, deserializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";

// Readable message from an Odoo RPC error.
function errorMessage(error, fallback) {
    return error?.data?.message || (typeof error?.message === "string" && error.message) || fallback;
}

// Popup "Versions": list with comments (editable), activate, restore as a new
// version, copy into a new report, delete (never the active version), and
// discard the draft when there is one.
export class VersionsDialog extends Component {
    static template = "report_studio.VersionsDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        reportId: Number,
        reportName: String,
        canWrite: Boolean,
        hasDraft: Boolean,
        onReload: Function,
        onOpenReport: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({ versions: [], copyNames: {}, hasDraft: this.props.hasDraft });
        onWillStart(() => this.load());
    }

    async load() {
        const versions = await this.orm.searchRead(
            "rs.report.version",
            [["report_id", "=", this.props.reportId]],
            ["version_no", "comment", "is_active", "user_id", "create_date"],
            { order: "version_no desc" }
        );
        this.state.versions = versions.map((v) => ({
            ...v,
            date: v.create_date ? formatDateTime(deserializeDateTime(v.create_date)) : "",
            author: v.user_id ? v.user_id[1] : "",
        }));
    }

    async call(method, ...args) {
        try {
            return await this.orm.call("rs.report", method, [[this.props.reportId], ...args]);
        } catch (error) {
            this.notification.add(errorMessage(error, _t("Change failed")), { type: "danger" });
            throw error;
        }
    }

    async onComment(version, ev) {
        await this.call("set_version_comment", version.id, ev.target.value);
        version.comment = ev.target.value;
    }

    // With a draft, activating or restoring a version discards it (the editor
    // shows the draft otherwise): ask first.
    confirmDiscardDraft() {
        if (!this.state.hasDraft) {
            return Promise.resolve(true);
        }
        return new Promise((resolve) => {
            this.dialog.add(
                ConfirmationDialog,
                {
                    title: _t("Discard the draft?"),
                    body: _t(
                        "There is a draft: activating or restoring a version discards it. Do you want to continue?"
                    ),
                    confirmLabel: _t("Discard the draft and continue"),
                    confirm: async () => {
                        await this.call("discard_draft");
                        this.state.hasDraft = false;
                        resolve(true);
                    },
                    cancel: () => resolve(false),
                },
                { onClose: () => resolve(false) }
            );
        });
    }

    async activate(version) {
        if (!(await this.confirmDiscardDraft())) {
            return;
        }
        await this.call("activate_version_by_id", version.id);
        this.notification.add(_t("Version %s is now the active one", version.version_no), {
            type: "success",
        });
        await this.load();
        await this.props.onReload();
    }

    async restore(version) {
        if (!(await this.confirmDiscardDraft())) {
            return;
        }
        await this.call("restore_version_by_id", version.id);
        this.notification.add(_t("Version restored as a new version"), { type: "success" });
        await this.load();
        await this.props.onReload();
    }

    async copy(version) {
        const name =
            (this.state.copyNames[version.id] || "").trim() ||
            _t("%s (copy)", this.props.reportName);
        const newId = await this.call("copy_version_by_id", version.id, name);
        this.props.close();
        await this.props.onOpenReport(newId);
        this.notification.add(_t("New report created from the copy"), { type: "success" });
    }

    delete(version) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete Version"),
            body: _t("Delete version %s? This cannot be undone.", version.version_no),
            confirmLabel: _t("Delete the version"),
            confirm: async () => {
                await this.call("delete_version_by_id", version.id);
                await this.load();
            },
            cancel: () => {},
        });
    }

    async discardDraft() {
        await this.call("discard_draft");
        this.state.hasDraft = false;
        this.notification.add(_t("Draft discarded"), { type: "info" });
        await this.props.onReload();
    }
}

// Popup of the Save button: new version or only the work in progress (draft,
// not printed), with the comment of the version.
export class SaveDialog extends Component {
    static template = "report_studio.SaveDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        comment: { type: String, optional: true },
        onSave: Function,
    };

    setup() {
        this.state = useState({ newVersion: true, comment: this.props.comment || "", saving: false });
    }

    async save() {
        this.state.saving = true;
        try {
            const done = await this.props.onSave({
                newVersion: this.state.newVersion,
                comment: this.state.comment.trim(),
            });
            if (done) {
                this.props.close();
            }
        } finally {
            this.state.saving = false;
        }
    }
}

// Popup "Save as Block": name and model of the reusable block.
export class SaveBlockDialog extends Component {
    static template = "report_studio.SaveBlockDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        caption: String,
        // [{model, label, prefix}]: the report model, or a linked model when all
        // the field paths of the block go through the same many2one field.
        models: Array,
        onSave: Function,
    };

    setup() {
        this.state = useState({
            name: "",
            choice: this.props.models.length - 1,
            saving: false,
        });
    }

    async save() {
        this.state.saving = true;
        try {
            const done = await this.props.onSave({
                name: this.state.name,
                option: this.props.models[this.state.choice],
            });
            if (done) {
                this.props.close();
            }
        } finally {
            this.state.saving = false;
        }
    }
}

// Popup asking which field links the document to the model of a reusable
// block (e.g. Customer or Delivery Address for a contact block).
export class LinkDialog extends Component {
    static template = "report_studio.LinkDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        blockName: String,
        links: Array,
        onChoose: Function,
    };

    get question() {
        return _t("Which data of the document should the block \"%s\" show?", this.props.blockName);
    }

    choose(link) {
        this.props.onChoose(link);
        this.props.close();
    }
}
