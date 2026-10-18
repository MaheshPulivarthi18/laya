<!-- Copyright 2026 Aayush Chawla -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<script lang="ts">
	// Banner under the title bar while a Corpus batch is being processed. The
	// engine works in the background; this reports the batch (current document,
	// done count, progress) and reopens the add sheet with the stage tiles.
	// When the batch finishes it stays until dismissed, like the update banner.
	import { corpusActivity, openCorpusSheet, clearFinishedSheetItems } from '$lib/stores/corpusSheet';
	import { documents } from '$lib/stores/documents';

	const active = $derived($corpusActivity.done < $corpusActivity.total);
	const failedAll = $derived($corpusActivity.done === $corpusActivity.total && $corpusActivity.failed > 0);

	function dismiss() {
		clearFinishedSheetItems((id) => $documents.find((d) => d.document_id === id)?.status);
	}
</script>

{#if $corpusActivity.total > 0}
	<div class="flex items-center justify-center gap-2 border-b px-4 py-1.5 {failedAll ? 'bg-amber-500/10 border-amber-500/25' : 'bg-laya-orange/10 border-laya-orange/25'}">
		{#if active}
			<svg class="h-3 w-3 shrink-0 animate-spin text-laya-orange" fill="none" viewBox="0 0 24 24">
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
				<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
			</svg>
			<span class="text-xs text-laya-orange">
				Adding to Corpus:
				{#if $corpusActivity.currentTitle}
					<span class="font-medium">{$corpusActivity.currentTitle}</span>
				{:else}
					{$corpusActivity.total - $corpusActivity.done} document{$corpusActivity.total - $corpusActivity.done === 1 ? '' : 's'}
				{/if}
			</span>
			<div class="h-1 w-24 overflow-hidden rounded-full bg-surface-700">
				<div class="h-full rounded-full bg-laya-orange transition-all" style="width: {Math.round($corpusActivity.ratio * 100)}%"></div>
			</div>
			<span class="text-xs tabular-nums text-surface-400">{$corpusActivity.done}/{$corpusActivity.total}</span>
		{:else if failedAll}
			<span class="text-xs text-amber-400">
				Corpus: {$corpusActivity.failed} of {$corpusActivity.total} document{$corpusActivity.total === 1 ? '' : 's'} failed
			</span>
		{:else}
			<span class="text-xs text-laya-orange">
				Corpus: {$corpusActivity.total} document{$corpusActivity.total === 1 ? '' : 's'} added
			</span>
		{/if}
		<button
			onclick={openCorpusSheet}
			class="ml-1 rounded-md px-2.5 py-0.5 text-xs font-medium transition-colors {failedAll ? 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30' : 'bg-laya-orange/20 text-laya-orange hover:bg-laya-orange/30'}"
		>
			Details
		</button>
		{#if !active}
			<button onclick={dismiss} class="ml-2 text-xs text-surface-500 transition-colors hover:text-surface-300" title="Dismiss">&times;</button>
		{/if}
	</div>
{/if}
