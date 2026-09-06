export function mobileContentPadding(safeTop: number, safeBottom: number) {
  return {
    paddingTop: 76 + Math.max(0, safeTop),
    paddingBottom: 96 + Math.max(0, safeBottom),
  };
}
