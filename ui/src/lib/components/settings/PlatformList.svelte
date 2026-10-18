<!-- Copyright 2026 Aayush Chawla -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<script lang="ts" module>
	import type { EgressConnection, PlatformConfig } from '$lib/api/types';

	export interface PlatformEntry {
		key: string;
		config: PlatformConfig;
		connections: EgressConnection[];
	}

	export interface PlatformGroup {
		category: string;
		label: string;
		items: PlatformEntry[];
	}
</script>

<script lang="ts">
	import PlatformIcon from './PlatformIcon.svelte';
	import { platformHealth, platformSummary, STATUS_STYLE, statusTint } from '$lib/utils/integrationHealth';

	let {
		groups,
		selectedKey,
		narrow,
		onSelect,
		onOpen
	}: {
		groups: PlatformGroup[];
		selectedKey: string | null;
		/** Drill-in layout: full-width rows with a summary line and a chevron,
		 *  and no row is shown as selected. */
		narrow: boolean;
		onSelect: (key: string) => void;
		/** Enter on the list, or a click in the narrow layout: open the detail. */
		onOpen: (key: string) => void;
	} = $props();

	const keys = $derived(groups.flatMap((g) => g.items.map((p) => p.key)));

	// Arrow keys, Home and End move the selection. They are handled on the
	// listbox element, so they only act while the list has focus and cannot
	// clash with the app's global shortcuts.
	function handleKeydown(e: KeyboardEvent) {
		if (keys.length === 0) return;
		const i = selectedKey ? keys.indexOf(selectedKey) : -1;
		let next: number | null = null;
		if (e.key === 'ArrowDown') next = Math.min(i + 1, keys.length - 1);
		else if (e.key === 'ArrowUp') next = Math.max(i - 1, 0);
		else if (e.key === 'Home') next = 0;
		else if (e.key === 'End') next = keys.length - 1;
		else if (e.key === 'Enter' && selectedKey) {
			e.preventDefault();
			onOpen(selectedKey);
			return;
		}
		if (next === null) return;
		e.preventDefault();
		onSelect(keys[next]);
		document.getElementById(`integ-option-${keys[next]}`)?.scrollIntoView({ block: 'nearest' });
	}
</script>

<div
	role="listbox"
	tabindex="0"
	aria-label="Integrations"
	aria-activedescendant={selectedKey ? `integ-option-${selectedKey}` : undefined}
	onkeydown={handleKeydown}
	class="flex flex-col px-2.5 py-4 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-laya-orange/50
		{narrow ? 'gap-[18px]' : 'gap-4 border-r-[0.5px] border-integ-line bg-integ-recess'}"
>
	{#each groups as group (group.category)}
		<div class="flex flex-col gap-0.5">
			<div class="px-2.5 pb-1.5 text-integ-label font-semibold uppercase tracking-[0.08em] text-integ-t4">
				{group.label}
			</div>
			{#each group.items as p (p.key)}
				{@const h = platformHealth(p.connections)}
				{@const selected = !narrow && p.key === selectedKey}
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<div
					id="integ-option-{p.key}"
					role="option"
					aria-selected={selected}
					tabindex="-1"
					onclick={() => (narrow ? onOpen(p.key) : onSelect(p.key))}
					class="flex cursor-pointer items-center gap-2.5 rounded-lg transition-colors hover:bg-integ-fill
						{narrow ? 'px-3 py-2.5' : 'px-2.5 py-[7px]'}
						{selected ? 'bg-integ-fill-2 shadow-[inset_0_0_0_0.5px_var(--color-integ-line)] hover:bg-integ-fill-2' : ''}"
				>
					<div
						class="grid shrink-0 place-items-center
							{narrow ? 'h-[30px] w-[30px] rounded-[7px]' : 'h-6 w-6 rounded-md'}
							{h.n ? 'bg-integ-fill-2 text-integ-t1' : 'bg-integ-fill text-integ-t4'}"
					>
						<PlatformIcon platform={p.key} size={narrow ? 16 : 14} />
					</div>
					<div class="flex min-w-0 flex-1 flex-col gap-0.5">
						<span
							class="truncate {narrow ? 'text-integ-item-lg' : 'text-integ-item'}
								{selected ? 'font-semibold' : 'font-medium'}
								{h.n ? 'text-integ-t1' : 'text-integ-t3'}"
						>
							{p.config.label}
						</span>
						{#if narrow}
							<span
								class="truncate text-integ-note {h.nBad > 0 ? '' : 'text-integ-t4'}"
								style:color={h.nBad > 0 ? STATUS_STYLE[h.worst].fg : undefined}
							>
								{platformSummary(p.connections)}
							</span>
						{/if}
					</div>
					{#if h.nBad > 0}
						<span
							class="grid h-[18px] min-w-[18px] place-items-center rounded-[9px] px-[5px] font-mono text-integ-label font-semibold"
							style:background={statusTint(h.worst, 0.18)}
							style:color={STATUS_STYLE[h.worst].fg}
							aria-label="{h.nBad} need attention"
						>
							{h.nBad}
						</span>
					{:else if h.health === 'ok'}
						<span class="flex items-center gap-[5px] font-mono text-integ-label text-integ-t4">
							<span class="h-1.5 w-1.5 rounded-full bg-[#22c55e]"></span>{h.n}
						</span>
					{/if}
					{#if narrow}
						<svg class="h-4 w-4 shrink-0 text-integ-t4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<path d="M9 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" />
						</svg>
					{/if}
				</div>
			{/each}
		</div>
	{/each}
</div>
