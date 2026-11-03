/*
 * Instant On monitor - dashboard widget.
 * Copyright (C) 2026 os-instanton contributors. BSD 2-Clause license.
 */
import BaseTableWidget from "./BaseTableWidget.js";

export default class InstantOn extends BaseTableWidget {
    constructor() {
        super();
        this.tickTimeout = 30;
    }

    getGridOptions() {
        return {
            sizeToContent: 650
        };
    }

    getMarkup() {
        let $container = $('<div></div>');
        let $table = this.createTable('instanton-table', {
            headerPosition: 'left'
        });
        $container.append($table);
        return $container;
    }

    _esc(value) {
        return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[c]);
    }

    async onWidgetTick() {
        const data = await this.ajaxCall('/api/instanton/status/summary');
        const t = this.translations;
        if (!data || !data.meta || !data.meta.generated) {
            this.updateTable('instanton-table', [[t.status, `<a href="/ui/instanton/index/settings">${t.nodata}</a>`]]);
            return;
        }
        const s = data.summary || {};
        const sw = data.switch || {};
        const ok = (v) => `<i class="fa fa-circle text-${v ? 'success' : 'danger'}"></i>`;
        const rows = [
            [t.switch, `${ok(s.switch_online)} <a href="/ui/instanton/index/switch">${s.switch_online
                ? `${s.ports_up} / ${s.ports_total} ${t.ports}` : t.offline}</a>` +
                (sw.temperature ? ` &middot; ${this._esc(sw.temperature)} &deg;C` : '')],
            [t.aps, `${ok(s.aps_total && s.aps_online === s.aps_total)} <a href="/ui/instanton/index/accesspoints">` +
                `${s.aps_online} / ${s.aps_total} ${t.online}</a>`],
            [t.clients, `<a href="/ui/instanton/index/clients">${s.clients_online}</a> ` +
                `(${s.clients_wireless} ${t.wireless}, ${s.clients_wired} ${t.wired})`]
        ];
        if (s.poe_w !== null && s.poe_w !== undefined) {
            rows.push([t.poe, `${this._esc(s.poe_w)} W (${this._esc(s.poe_percent)}%)`]);
        }
        const problems = (data.insights || []).filter((i) => i.level !== 'info');
        rows.push([t.checks, problems.length
            ? problems.slice(0, 3).map((i) => `<div class="text-${i.level === 'critical' ? 'danger' : 'warning'}">` +
                `<i class="fa fa-exclamation-triangle"></i> ${this._esc(i.title)}</div>`).join('') +
                (problems.length > 3 ? `<a href="/ui/instanton/">+${problems.length - 3} ${t.more}</a>` : '')
            : `<span class="text-success"><i class="fa fa-check"></i> ${t.allgood}</span>`]);
        this.updateTable('instanton-table', rows);
    }
}
