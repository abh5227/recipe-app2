// The pure reorder op for the album drag (Stage 4 build 3d-iii). Move `id` to sit immediately BEFORE
// `beforeId` in the ordered id-list — or to the END when `beforeId` is null (dropped past the last photo).
// Returns a NEW array; the input is never mutated. This is exactly what a drop does (remove the dragged id,
// reinsert at the drop point), so it's kept pure and unit-tested (tests/js/reorder.test.js). Defensive:
// a no-op drop (beforeId === id) or an unknown beforeId leaves the order effectively unchanged / appends.
export function reorderBefore(order, id, beforeId) {
  if (id === beforeId) return [...order];                 // dropped onto itself -> no move
  const without = order.filter((x) => x !== id);
  if (beforeId == null) return [...without, id];          // dropped at the end
  const at = without.indexOf(beforeId);
  if (at < 0) return [...without, id];                    // beforeId not found (defensive) -> append
  return [...without.slice(0, at), id, ...without.slice(at)];
}
