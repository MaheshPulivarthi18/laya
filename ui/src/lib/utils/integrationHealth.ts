// Copyright 2026 Aayush Chawla
// SPDX-License-Identifier: Apache-2.0

import type { EgressConnection } from '$lib/api/types';

export type ConnectionStatus = EgressConnection['status'];

/** Rolled-up state of one platform's accounts.
 *  'none' = no accounts, 'ok' = all connected, 'partial' = some failing,
 *  'down' = all failing. */
export type Health = 'none' | 'ok' | 'partial' | 'down';

export interface PlatformHealth {
	n: number;
	nBad: number;
	/** The most severe status among the accounts: error > expired > connected. */
	worst: ConnectionStatus;
	health: Health;
}

/** Summarise a platform's accounts. The worst status wins, so one failing
 *  account is never hidden behind a healthy one. Every place that shows a
 *  platform's state (list badge, detail legend, Settings tab dot) uses this. */
export function platformHealth(conns: EgressConnection[]): PlatformHealth {
	const n = conns.length;
	const nBad = conns.filter((c) => c.status !== 'connected').length;
	const worst: ConnectionStatus = conns.some((c) => c.status === 'error')
		? 'error'
		: conns.some((c) => c.status === 'expired')
			? 'expired'
			: 'connected';
	const health: Health = n === 0 ? 'none' : nBad === 0 ? 'ok' : nBad === n ? 'down' : 'partial';
	return { n, nBad, worst, health };
}

/** Colours and label per status. `dot` and `rgb` are the same in both themes;
 *  `fg` is a theme-aware text colour token defined in app.css. Tints are
 *  built as `rgb(<rgb> / <alpha>)`. */
export const STATUS_STYLE: Record<
	ConnectionStatus,
	{ dot: string; rgb: string; fg: string; label: string }
> = {
	connected: { dot: '#22c55e', rgb: '34 197 94', fg: 'var(--color-integ-ok-fg)', label: 'Connected' },
	error: { dot: '#ef4444', rgb: '239 68 68', fg: 'var(--color-integ-err-fg)', label: 'Error' },
	expired: { dot: '#f59e0b', rgb: '245 158 11', fg: 'var(--color-integ-exp-fg)', label: 'Expired' }
};

/** Tint of a status colour at the given opacity, for backgrounds and borders. */
export function statusTint(status: ConnectionStatus, alpha: number): string {
	return `rgb(${STATUS_STYLE[status].rgb} / ${alpha})`;
}

/** One-line summary of a platform's accounts, e.g. "3 accounts",
 *  "2 of 3 need attention", "All 3 failing" or "Not connected". */
export function platformSummary(conns: EgressConnection[]): string {
	const { n, nBad, health } = platformHealth(conns);
	if (health === 'none') return 'Not connected';
	if (n === 1) {
		const c = conns[0];
		return c.status === 'connected' ? c.name : `${c.name} · ${STATUS_STYLE[c.status].label}`;
	}
	if (health === 'ok') return `${n} accounts`;
	if (health === 'partial') return `${nBad} of ${n} need attention`;
	return `All ${n} failing`;
}

/** Count per status, omitting zeros, e.g. "1 connected · 1 error · 1 expired". */
export function healthLegend(conns: EgressConnection[]): string {
	return (['connected', 'error', 'expired'] as const)
		.map((s) => [s, conns.filter((c) => c.status === s).length] as const)
		.filter(([, count]) => count > 0)
		.map(([s, count]) => `${count} ${STATUS_STYLE[s].label.toLowerCase()}`)
		.join(' · ');
}

/** Platform to select when the Integrations tab opens: the first with a
 *  failing account, else the first with any account, else the first. */
export function defaultPlatform(
	platforms: { key: string; connections: EgressConnection[] }[]
): string | null {
	const failing = platforms.find((p) => platformHealth(p.connections).nBad > 0);
	const connected = platforms.find((p) => p.connections.length > 0);
	return (failing ?? connected ?? platforms[0])?.key ?? null;
}
