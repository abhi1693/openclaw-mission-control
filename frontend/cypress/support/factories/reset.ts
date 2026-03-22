let _counter = 0;

export function nextId(prefix: string): string {
  return `${prefix}-${++_counter}`;
}

export function resetFactoryState(): void {
  _counter = 0;
}
