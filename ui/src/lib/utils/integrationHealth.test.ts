// Copyright 2026 Aayush Chawla
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from 'vitest';
import type { EgressConnection } from '$lib/api/types';
import { defaultPlatform, healthLegend, platformHealth, platformSummary } from './integrationHealth';

function conn(name: string, status: EgressConnection['status']): EgressConnection {
	return {
		connection_id: `conn_${name}`,
		platform: 'gmail',
		name,
		status,
		capabilities: [],
		created_at: '2026-01-01 00:00:00'
	};
}

describe('platformHealth', () => {
	it('reports none for a platform without accounts', () => {
		expect(platformHealth([])).toEqual({ n: 0, nBad: 0, worst: 'connected', health: 'none' });
	});

	it('does not let a healthy account hide failing ones', () => {
		const h = platformHealth([conn('Laya', 'connected'), conn('Work', 'error'), conn('Me', 'expired')]);
		expect(h).toEqual({ n: 3, nBad: 2, worst: 'error', health: 'partial' });
	});

	it('ranks expired below error and above connected', () => {
		expect(platformHealth([conn('a', 'connected'), conn('b', 'expired')]).worst).toBe('expired');
	});

	it('reports down when every account fails', () => {
		expect(platformHealth([conn('a', 'expired'), conn('b', 'expired')]).health).toBe('down');
	});
});

describe('platformSummary', () => {
	it.each([
		[[], 'Not connected'],
		[[conn('Laya', 'connected')], 'Laya'],
		[[conn('Work', 'error')], 'Work · Error'],
		[[conn('a', 'connected'), conn('b', 'connected'), conn('c', 'connected')], '3 accounts'],
		[[conn('a', 'connected'), conn('b', 'error'), conn('c', 'expired')], '2 of 3 need attention'],
		[[conn('a', 'error'), conn('b', 'error'), conn('c', 'expired')], 'All 3 failing']
	])('summarises %j as %s', (conns, expected) => {
		expect(platformSummary(conns as EgressConnection[])).toBe(expected);
	});
});

describe('healthLegend', () => {
	it('counts each status and omits zeros', () => {
		expect(healthLegend([conn('a', 'connected'), conn('b', 'error'), conn('c', 'expired')])).toBe(
			'1 connected · 1 error · 1 expired'
		);
		expect(healthLegend([conn('a', 'connected'), conn('b', 'connected')])).toBe('2 connected');
	});
});

describe('defaultPlatform', () => {
	it('prefers a failing platform, then a connected one, then the first', () => {
		const empty = { key: 'slack', connections: [] };
		const ok = { key: 'linear', connections: [conn('a', 'connected')] };
		const bad = { key: 'gmail', connections: [conn('a', 'connected'), conn('b', 'error')] };
		expect(defaultPlatform([empty, ok, bad])).toBe('gmail');
		expect(defaultPlatform([empty, ok])).toBe('linear');
		expect(defaultPlatform([empty])).toBe('slack');
		expect(defaultPlatform([])).toBeNull();
	});
});
