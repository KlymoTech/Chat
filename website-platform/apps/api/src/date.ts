export function addDays(d: Date, days: number): Date {
  return new Date(d.getTime() + days * 86_400_000);
}
