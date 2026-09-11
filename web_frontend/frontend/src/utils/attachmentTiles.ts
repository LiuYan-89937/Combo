/**
 * Fixed geometry for attachment thumbnails.
 *
 * Attachments used to be sized from each file's own dimensions (a lone image
 * rendered large, several images changed column counts), which is what made a
 * multi-attachment turn look ragged. Every thumbnail is now the same square at
 * the same gap, so any number of attachments lines up in a regular row.
 *
 * The reference layout measures 160px tiles with a 16px gap at 2x DPR, i.e. an
 * 80px square on an 8px gap; 8px also matches `--app-radius-sm`, so the corner
 * radius reuses the existing design token.
 */
export const ATTACHMENT_TILE_SIZE = 80
export const ATTACHMENT_TILE_GAP = 8

/** CSS custom properties consumed by the tile styles in each attachment view. */
export function attachmentTileVars(): Record<string, string> {
  return {
    '--attachment-tile-size': `${ATTACHMENT_TILE_SIZE}px`,
    '--attachment-tile-gap': `${ATTACHMENT_TILE_GAP}px`,
  }
}
