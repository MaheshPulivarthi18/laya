<!-- Copyright 2026 Aayush Chawla -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<script lang="ts">
	import { tick, untrack } from 'svelte';
	import { slide } from 'svelte/transition';
	import { page } from '$app/state';
	import { engineApi } from '$lib/api/engine';
	import { glassTheme } from '$lib/stores/glassTheme';
	import { reducedMotion } from '$lib/stores/reducedMotion';
	import { setIntegrationErrorsFromConnections } from '$lib/stores/integrationErrors';
	import { defaultPlatform } from '$lib/utils/integrationHealth';
	import PlatformList, { type PlatformEntry, type PlatformGroup } from './PlatformList.svelte';
	import PlatformDetail from './PlatformDetail.svelte';
	import ConnectModal from './ConnectModal.svelte';
	import N8nAdvancedSection from './N8nAdvancedSection.svelte';
	import type { PlatformConfig, EgressConnection } from '$lib/api/types';

	// Platform registry + connections
	let platforms = $state<Record<string, PlatformConfig>>({});
	let connections = $state<EgressConnection[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Selected platform. It is kept across refreshes (test, remove, connect),
	// so the detail pane stays on the platform the user was looking at.
	let selectedKey = $state<string | null>(null);

	// Narrow layout: below 900px of this pane's own width (not the viewport,
	// since the chat pane can squeeze Settings), the list and detail become
	// two drill-in views. `showDetail` says which one is visible.
	let paneWidth = $state(0);
	const narrow = $derived(paneWidth > 0 && paneWidth < 900);
	let showDetail = $state(false);

	let detailHeading = $state<HTMLElement>();

	// Connect modal: add a new account, or reconnect an existing one in place.
	let modal = $state<{ entry: PlatformEntry; mode: 'add' | 'reconnect'; connection?: EgressConnection } | null>(
		null
	);

	// n8n advanced section
	let showN8nAdvanced = $state(false);

	// Category config
	const CATEGORY_ORDER = ['development', 'project_management', 'communication', 'email', 'calendar'];
	const CATEGORY_LABELS: Record<string, string> = {
		development: 'Development',
		project_management: 'Project Management',
		communication: 'Communication',
		email: 'Email',
		calendar: 'Calendar'
	};

	// SMTP is not in the engine's platform registry; the pane lists it as a
	// platform of its own under Email.
	const SMTP_CONFIG: PlatformConfig = {
		label: 'Email (SMTP)',
		category: 'email',
		icon: 'smtp',
		n8n_type: '',
		n8n_node: '',
		oauth: false,
		fields: []
	};

	// Load data on mount (once). loadData() reads `platforms` to decide
	// whether to show the loading skeleton, which Svelte 5 would track as
	// a dependency — then setting `platforms` after the fetch re-triggers
	// the effect, creating an infinite request loop. Using untrack prevents this.
	$effect(() => {
		untrack(() => loadData());
	});

	async function loadData() {
		// Only show the full loading skeleton on initial load; refreshes
		// (e.g. after disconnect) update in-place to preserve scroll position.
		const isInitial = platforms && Object.keys(platforms).length === 0;
		if (isInitial) loading = true;
		error = null;
		try {
			const [platformsResp, connectionsResp] = await Promise.all([
				engineApi.getPlatforms(),
				engineApi.listEgressConnections()
			]);
			platforms = platformsResp.platforms;
			connections = connectionsResp.connections;
			// Re-seed the Integrations/Settings red dot from this fresh list so
			// fixing or breaking a connection here updates the dot immediately
			// (connect / test / disconnect all funnel through loadData).
			setIntegrationErrorsFromConnections(connections);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load integrations';
		} finally {
			loading = false;
		}
	}

	const groups = $derived.by(() => {
		const result: PlatformGroup[] = [];
		for (const cat of CATEGORY_ORDER) {
			const items: PlatformEntry[] = [];
			for (const [key, config] of Object.entries(platforms)) {
				if (config.category === cat) {
					items.push({ key, config, connections: connections.filter((c) => c.platform === key) });
				}
			}
			if (cat === 'email') {
				items.push({
					key: 'smtp',
					config: SMTP_CONFIG,
					connections: connections.filter((c) => c.platform === 'smtp')
				});
			}
			if (items.length > 0) {
				result.push({ category: cat, label: CATEGORY_LABELS[cat] || cat, items });
			}
		}
		return result;
	});

	const entries = $derived(groups.flatMap((g) => g.items));

	// Pick the selection once the platforms arrive: `?integration=<key>` from
	// the URL (so links can point at a broken platform), else the default rule
	// in defaultPlatform(). A selection whose platform disappears is replaced.
	// It waits for the first load: SMTP is listed even while the registry is
	// still empty, and choosing then would always select SMTP.
	$effect(() => {
		if (loading || entries.length === 0) return;
		const current = untrack(() => selectedKey);
		if (current && entries.some((p) => p.key === current)) return;
		const fromUrl = page.url.searchParams.get('integration');
		const linked = fromUrl && entries.some((p) => p.key === fromUrl) ? fromUrl : null;
		selectedKey = linked ?? defaultPlatform(entries);
		if (linked) showDetail = true;
	});

	const selected = $derived(entries.find((p) => p.key === selectedKey) ?? null);

	async function openDetail(key: string) {
		selectedKey = key;
		showDetail = true;
		await tick();
		detailHeading?.focus();
	}

	function openAdd(entry: PlatformEntry) {
		modal = { entry, mode: 'add' };
	}

	function openReconnect(entry: PlatformEntry, connection: EgressConnection) {
		modal = { entry, mode: 'reconnect', connection };
	}

	function handleConnected() {
		modal = null;
		loadData();
	}
</script>

<div bind:clientWidth={paneWidth} class="space-y-8 {$glassTheme ? '' : 'integ-solid'}">
	{#if error}
		<div class="rounded-lg border border-red-800 bg-red-900/30 px-4 py-2 text-laya-base text-red-300">
			{error}
		</div>
	{/if}

	<div
		class="grid overflow-hidden rounded-[14px]
			{narrow ? 'grid-cols-[minmax(0,1fr)]' : 'min-h-[680px] grid-cols-[290px_minmax(0,1fr)]'}
			{$glassTheme ? 'glass-section' : 'border border-surface-700 bg-surface-800'}"
	>
		{#if loading}
			<!-- Skeleton that mirrors the layout; shown on the first load only. -->
			{#if !narrow}
				<div class="flex flex-col gap-1.5 border-r-[0.5px] border-integ-line bg-integ-recess px-3.5 py-[18px]">
					<span class="mx-1.5 mb-2 h-[9px] w-[90px] rounded bg-integ-skel"></span>
					{#each [96, 120, 84, 0, 70, 104, 0, 88, 132] as w, i (i)}
						<div class="integ-pulse flex items-center gap-2.5 px-1.5 py-[7px]">
							<span class="h-6 w-6 rounded-md bg-integ-skel"></span>
							<span class="h-2.5 rounded bg-integ-skel" style:width="{w}px"></span>
						</div>
					{/each}
				</div>
			{/if}
			<div class="integ-pulse flex flex-col gap-5 px-7 py-6">
				<div class="flex items-center gap-4">
					<span class="h-[46px] w-[46px] rounded-[11px] bg-integ-skel"></span>
					<div class="flex flex-1 flex-col gap-2">
						<span class="h-3.5 w-[140px] rounded-[5px] bg-integ-skel"></span>
						<span class="h-2.5 w-[200px] rounded bg-integ-skel"></span>
					</div>
					<span class="h-8 w-[116px] rounded-lg bg-integ-skel"></span>
				</div>
				<span class="h-1 rounded-sm bg-integ-skel"></span>
				<span class="h-[170px] rounded-[11px] bg-integ-skel"></span>
				<span class="h-[170px] rounded-[11px] bg-integ-skel"></span>
			</div>
		{:else}
			{#if !narrow || !showDetail}
				<PlatformList
					{groups}
					{selectedKey}
					{narrow}
					onSelect={(key) => (selectedKey = key)}
					onOpen={openDetail}
				/>
			{/if}
			{#if selected && (!narrow || showDetail)}
				<PlatformDetail
					platform={selected}
					{narrow}
					bind:headingEl={detailHeading}
					onBack={() => (showDetail = false)}
					onAdd={() => openAdd(selected)}
					onReconnect={(conn) => openReconnect(selected, conn)}
					onRefresh={loadData}
				/>
			{/if}
		{/if}
	</div>

	<!-- n8n Advanced Section -->
	<div class="{$glassTheme ? 'glass-section' : 'rounded-lg border border-surface-700 bg-surface-800'}">
		<button
			onclick={() => (showN8nAdvanced = !showN8nAdvanced)}
			class="flex w-full items-center justify-between p-4 text-left transition-colors {$glassTheme ? 'hover:bg-white/[0.04]' : 'hover:bg-surface-700/50'}"
		>
			<div>
				<span class="text-laya-base font-medium text-surface-300">Advanced: n8n Workflow Engine</span>
				<span class="ml-2 text-laya-secondary text-surface-500">Manage workflows, webhooks, and n8n configuration</span>
			</div>
			<svg
				class="h-4 w-4 text-surface-400 transition-transform {showN8nAdvanced ? 'rotate-180' : ''}"
				fill="none"
				viewBox="0 0 24 24"
				stroke="currentColor"
			>
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
			</svg>
		</button>

		{#if showN8nAdvanced}
			<div transition:slide={{ duration: $reducedMotion ? 0 : 200 }} class="border-t border-surface-700 p-5">
				<N8nAdvancedSection />
			</div>
		{/if}
	</div>

	<!-- Connect Modal -->
	{#if modal}
		<ConnectModal
			platform={modal.entry.key}
			platformLabel={modal.entry.config.label}
			isOAuth={modal.entry.config.oauth}
			fields={modal.entry.config.fields}
			mode={modal.mode}
			connection={modal.connection}
			onClose={() => {
				// A sign-in can still complete, or end with a new error, after
				// the modal closes; reload so the cards show the current state.
				modal = null;
				loadData();
			}}
			onConnected={handleConnected}
		/>
	{/if}
</div>
