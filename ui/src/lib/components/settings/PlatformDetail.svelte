<!-- Copyright 2026 Aayush Chawla -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<script lang="ts">
	import PlatformIcon from './PlatformIcon.svelte';
	import AccountCard from './AccountCard.svelte';
	import { healthLegend, platformHealth, STATUS_STYLE } from '$lib/utils/integrationHealth';
	import type { EgressConnection } from '$lib/api/types';
	import type { PlatformEntry } from './PlatformList.svelte';

	let {
		platform,
		narrow,
		headingEl = $bindable(),
		onBack,
		onAdd,
		onReconnect,
		onRefresh
	}: {
		platform: PlatformEntry;
		narrow: boolean;
		/** The title element; the list moves focus here when Enter is pressed. */
		headingEl?: HTMLElement;
		onBack: () => void;
		onAdd: () => void;
		onReconnect: (conn: EgressConnection) => void;
		onRefresh: () => void;
	} = $props();

	// Body copy for the empty state where a platform needs more than the generic line.
	const EMPTY_TEXT: Record<string, string> = {
		slack:
			'Connect a workspace and pick the channels Laya should watch. Messages there become Pulse items, and Laya can reply or react for you. You can connect more than one workspace.',
		discord:
			'Connect a bot token and Laya will ingest from the servers it is in. You can connect more than one bot.',
		smtp: 'Add any mailbox over IMAP/SMTP. Use this for providers without OAuth.'
	};

	const h = $derived(platformHealth(platform.connections));
	const label = $derived(platform.config.label);
	const subtitle = $derived(
		`${platform.config.oauth ? 'OAuth' : 'Credentials'} · ${
			h.n === 0 ? 'not connected' : h.n === 1 ? '1 account' : `${h.n} accounts`
		}`
	);
</script>

<div class="flex min-w-0 flex-col gap-5 {narrow ? 'px-5 pb-6 pt-5' : 'px-7 pb-7 pt-6'}">
	{#if narrow}
		<button
			onclick={onBack}
			class="-mb-1.5 -mt-1 flex items-center gap-1.5 self-start text-integ-body font-medium text-integ-t3 transition-colors hover:text-integ-t1"
		>
			<svg class="h-[15px] w-[15px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
				<path d="M15 19l-7-7 7-7" stroke-linecap="round" stroke-linejoin="round" />
			</svg>
			All integrations
		</button>
	{/if}

	<div class="flex flex-wrap items-center gap-4">
		<div class="grid h-[46px] w-[46px] shrink-0 place-items-center rounded-[11px] bg-integ-fill-2 text-integ-t1">
			<PlatformIcon platform={platform.key} size={22} />
		</div>
		<div class="flex min-w-[160px] flex-1 flex-col gap-[3px]">
			<h3
				bind:this={headingEl}
				tabindex="-1"
				class="text-integ-title font-semibold tracking-[-0.01em] text-integ-t1 outline-none"
			>
				{label}
			</h3>
			<span class="text-integ-body text-integ-t3">{subtitle}</span>
		</div>
		<button
			onclick={onAdd}
			class="rounded-lg bg-laya-orange px-3.5 py-[7px] text-integ-body font-semibold text-integ-on-accent transition-colors hover:bg-laya-gold"
		>
			{h.n > 0 ? '+ Add account' : `Connect ${label}`}
		</button>
	</div>

	{#if h.n > 0}
		<!-- Health strip: one bar per account, coloured by its status. -->
		<div class="flex flex-col gap-2">
			<div class="flex gap-1" aria-hidden="true">
				{#each platform.connections as c (c.connection_id)}
					<span class="h-1 flex-1 rounded-sm" style:background={STATUS_STYLE[c.status].dot}></span>
				{/each}
			</div>
			<span
				class="text-integ-body {h.health === 'ok' ? 'text-integ-t3' : ''}"
				style:color={h.health === 'ok' ? undefined : STATUS_STYLE[h.worst].fg}
			>
				{healthLegend(platform.connections)}
			</span>
		</div>

		<div class="flex flex-col gap-2.5">
			{#each platform.connections as conn (conn.connection_id)}
				<AccountCard
					{conn}
					platformKey={platform.key}
					platformLabel={label}
					canReconnect={platform.config.oauth}
					{onReconnect}
					{onRefresh}
				/>
			{/each}
		</div>
	{:else}
		<div class="flex flex-1 flex-col items-start justify-center gap-2 px-1 pb-20 pt-10">
			<span class="text-integ-name font-semibold text-integ-t2">No {label} accounts yet</span>
			<span class="max-w-[440px] text-integ-body leading-[1.6] text-integ-t3 [text-wrap:pretty]">
				{EMPTY_TEXT[platform.key] ??
					'Connect an account and Laya will ingest from it and offer its actions in Pulse.'}
			</span>
		</div>
	{/if}
</div>
