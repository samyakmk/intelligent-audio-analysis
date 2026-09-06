/** A tiny latest-request-wins gate for async UI resources. */
export class RequestGeneration {
  private value = 0;

  begin(): number {
    this.value += 1;
    return this.value;
  }

  invalidate(): void {
    this.value += 1;
  }

  isCurrent(candidate: number): boolean {
    return candidate === this.value;
  }
}
