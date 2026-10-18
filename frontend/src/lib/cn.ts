/** Joins class names, skipping falsy values. Small on purpose: no tailwind-merge needed. */
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
