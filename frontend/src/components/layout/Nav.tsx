const LINKS = [
  { href: "#orders", label: "Test orders" },
  { href: "#how", label: "How it works" },
  { href: "#summary", label: "Call summary" },
];

export function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-paper">
      <a
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-tag focus:bg-ink focus:px-4 focus:py-2 focus:text-paper-white"
        href="#console"
      >
        Skip to the voice console
      </a>
      <nav
        aria-label="Main"
        className="mx-auto flex h-[var(--nav-height)] max-w-6xl items-center justify-between gap-6 px-5 sm:px-8"
      >
        <a className="flex items-baseline gap-2" href="#top">
          <span className="font-display text-2xl leading-none tracking-[-0.01em]">Aura</span>
          <span className="text-sm text-ink-muted">Skincare support</span>
        </a>

        <ul className="hidden items-center gap-8 text-[0.95rem] text-ink-muted md:flex">
          {LINKS.map((link) => (
            <li key={link.href}>
              <a className="transition-colors duration-200 hover:text-ink" href={link.href}>
                {link.label}
              </a>
            </li>
          ))}
        </ul>

        <a
          className="inline-flex min-h-11 items-center rounded-full bg-olive px-5 text-[0.95rem] font-medium text-paper-white transition-colors duration-200 hover:bg-olive-deep"
          href="#console"
        >
          Call Aria
        </a>
      </nav>
    </header>
  );
}
