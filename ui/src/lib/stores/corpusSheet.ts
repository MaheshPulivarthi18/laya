// Copyright 2026 Aayush Chawla
// SPDX-License-Identifier: Apache-2.0

// State for the "Add to Corpus" sheet: the files or paths the user dropped or
// picked, one tile each, and whether the sheet is open. Opened from the
// app-wide drop handler in the root layout, from the Corpus page and from the
// chat composer.

import { derived, get, writable } from 'svelte/store';
import { documentProgress, documents } from './documents';

export interface SheetItem {
	key: string;
	name: string;
	/** Browser drop or picker: the blob to upload (engine keeps a copy). */
	file?: File;
	/** Tauri drop or native picker: the path the engine reads in place. */
	path?: string;
	/** Set once the engine accepted the item. */
	documentId?: string;
	duplicate?: boolean;
	error?: string;
	errorCode?: string;
	submitting?: boolean;
}

export interface CorpusSheetState {
	open: boolean;
	items: SheetItem[];
}

export const corpusSheet = writable<CorpusSheetState>({ open: false, items: [] });

let seq = 0;

function nameOf(path: string): string {
	return path.split(/[\\/]/).pop() || path;
}

/** Tiles still pending or in flight; finished ones from an earlier batch are
 *  dropped when a new drop arrives so the counters describe one batch. */
function unfinished(items: SheetItem[]): SheetItem[] {
	const docs = get(documents);
	return items.filter(
		(it) => !isFinishedItem(it, it.documentId ? docs.find((d) => d.document_id === it.documentId)?.status : undefined)
	);
}

export function openCorpusSheetWithFiles(files: File[]): void {
	corpusSheet.update((s) => ({
		open: true,
		items: [...unfinished(s.items), ...files.map((file) => ({ key: `f${++seq}`, name: file.name, file }))]
	}));
}

export function openCorpusSheetWithPaths(paths: string[]): void {
	corpusSheet.update((s) => ({
		open: true,
		items: [...unfinished(s.items), ...paths.map((path) => ({ key: `p${++seq}`, name: nameOf(path), path }))]
	}));
}

/** Open the sheet with no files, for the picker and the empty state. */
export function openCorpusSheet(): void {
	corpusSheet.update((s) => ({ ...s, open: true }));
}

/** Hide the sheet. Items stay so the footer indicator keeps reporting on
 *  them and reopening shows the same tiles; processing continues on the engine. */
export function closeCorpusSheet(): void {
	corpusSheet.update((s) => ({ ...s, open: false }));
}

/** True when a tile has nothing left to wait for: rejected by the engine,
 *  reached a terminal status, or its document was deleted while in flight
 *  (``status`` is undefined because the row is gone from the store). */
export function isFinishedItem(it: SheetItem, status: string | undefined): boolean {
	if (it.error) return true;
	if (!it.documentId) return false;
	return status === undefined || status === 'ready' || status === 'failed';
}

/** Drop every finished tile. */
export function clearFinishedSheetItems(getStatus: (documentId: string) => string | undefined): void {
	corpusSheet.update((s) => ({
		...s,
		items: s.items.filter((it) => !isFinishedItem(it, it.documentId ? getStatus(it.documentId) : undefined))
	}));
}

/** Progress summary of the current batch, for the footer indicator. */
export interface CorpusActivity {
	total: number;
	/** Tiles that reached a terminal state (ready, failed, or rejected). */
	done: number;
	failed: number;
	/** 0..1 across the batch: terminal tiles count as 1, an embedding tile as its batch fraction. */
	ratio: number;
	/** Title of the tile currently being worked on, when exactly one is active. */
	currentTitle: string | null;
}

export const corpusActivity = derived(
	[corpusSheet, documents, documentProgress],
	([$sheet, $docs, $progress]): CorpusActivity => {
		const total = $sheet.items.length;
		let done = 0;
		let failed = 0;
		let sum = 0;
		const active: string[] = [];
		for (const it of $sheet.items) {
			if (it.error) {
				done += 1;
				failed += 1;
				sum += 1;
				continue;
			}
			const doc = it.documentId ? $docs.find((d) => d.document_id === it.documentId) : undefined;
			if (it.documentId && !doc) {
				// Deleted while in flight: nothing left to wait for.
				done += 1;
				sum += 1;
			} else if (doc?.status === 'ready') {
				done += 1;
				sum += 1;
			} else if (doc?.status === 'failed') {
				done += 1;
				failed += 1;
				sum += 1;
			} else {
				active.push(doc?.title ?? it.name);
				const prog = doc ? $progress[doc.document_id] : undefined;
				if (doc?.status === 'embedding' && prog?.total) sum += 0.4 + 0.5 * ((prog.done ?? 0) / prog.total);
				else if (doc?.status === 'linking' || doc?.status === 'summarizing') sum += 0.9;
				else if (doc?.status === 'parsing' || doc?.status === 'chunking') sum += 0.2;
				else if (doc) sum += 0.1;
			}
		}
		return {
			total,
			done,
			failed,
			ratio: total ? sum / total : 0,
			currentTitle: active.length === 1 ? active[0] : null
		};
	}
);

export function updateSheetItem(key: string, patch: Partial<SheetItem>): void {
	corpusSheet.update((s) => ({
		...s,
		items: s.items.map((it) => (it.key === key ? { ...it, ...patch } : it))
	}));
}

export function removeSheetItem(key: string): void {
	corpusSheet.update((s) => ({ ...s, items: s.items.filter((it) => it.key !== key) }));
}
