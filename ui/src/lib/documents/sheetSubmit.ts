// Copyright 2026 Aayush Chawla
// SPDX-License-Identifier: Apache-2.0

// Sends the add-sheet's pending tiles to the engine. Lives outside the sheet
// component so a batch keeps going after the sheet is dismissed; the engine
// processes each accepted document in the background and the documents store
// tracks its stages over the WebSocket.

import { get } from 'svelte/store';
import { corpusSheet, updateSheetItem } from '$lib/stores/corpusSheet';
import { uploadFile, uploadPath } from './upload';

let running = false;

/** Submit every pending tile, one at a time. Safe to call repeatedly. */
export async function submitPendingSheetItems(spaceId: string, title?: string): Promise<void> {
	if (running) return;
	running = true;
	try {
		for (;;) {
			const next = get(corpusSheet).items.find((it) => !it.documentId && !it.error && !it.submitting);
			if (!next) break;
			updateSheetItem(next.key, { submitting: true, error: undefined });
			const outcome = next.path
				? await uploadPath(next.path, spaceId, title)
				: next.file
					? await uploadFile(next.file, spaceId, title)
					: { name: next.name, error: 'Nothing to upload' };
			updateSheetItem(next.key, {
				submitting: false,
				documentId: outcome.document?.document_id,
				duplicate: outcome.duplicate,
				error: outcome.error,
				errorCode: outcome.errorCode
			});
		}
	} finally {
		running = false;
	}
}
