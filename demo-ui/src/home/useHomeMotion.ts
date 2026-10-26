import { useLayoutEffect, useEffect, type RefObject } from 'react';

export function useHomeMotion(rootRef: RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const root = document.documentElement;
    const previousTitle = document.title;
    root.dataset.surface = 'home';
    document.title = 'Tabula — Know what to order';

    return () => {
      delete root.dataset.surface;
      document.title = previousTitle;
    };
  }, []);

  useLayoutEffect(() => {
    const scope = rootRef.current;
    if (!scope) return;
    scope.querySelectorAll<HTMLElement>('[data-i]').forEach((node) => {
      const index = node.getAttribute('data-i');
      if (index) node.style.setProperty('--i', index);
    });
  }, [rootRef]);

  useEffect(() => {
    const scope = rootRef.current;
    if (!scope) return undefined;

    const header = scope.querySelector('.header');
    const navLinks = [...scope.querySelectorAll<HTMLAnchorElement>('.nav__link')];
    const sections = [...scope.querySelectorAll<HTMLElement>('[data-section]')];
    const scrubNodes = [...scope.querySelectorAll<HTMLElement>('[data-scrub]')];
    const revealNodes = [...scope.querySelectorAll<HTMLElement>('[data-reveal]')];
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');

    let revealObserver: IntersectionObserver | null = null;
    if (!('IntersectionObserver' in window)) {
      revealNodes.forEach((node) => node.classList.add('is-in'));
    } else {
      revealObserver = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            entry.target.classList.add('is-in');
            revealObserver?.unobserve(entry.target);
          });
        },
        { rootMargin: '0px 0px -10% 0px', threshold: 0.16 },
      );
      revealNodes.forEach((node) => revealObserver?.observe(node));
    }

    const updateScrub = () => {
      const height = window.innerHeight || 1;
      const still = reduce.matches;
      const room = Math.max(0, document.documentElement.scrollHeight - height - window.scrollY);
      scrubNodes.forEach((node) => {
        if (still) {
          node.style.setProperty('--scrub', '1');
          return;
        }
        const rect = node.getBoundingClientRect();
        const start = height * 0.92;
        const end = height * 0.38;
        // A block at the bottom of the page cannot travel up to the usual
        // finish line. Finish the highlight when the page can scroll no further.
        const targetEnd = Math.max(end, rect.top - room);
        const span = start - targetEnd;
        const progress = span <= 1 ? 1 : (start - rect.top) / span;
        const scrub = Math.min(1, Math.max(0, progress));
        node.style.setProperty('--scrub', scrub.toFixed(3));
      });
    };

    const clearNav = () => {
      navLinks.forEach((link) => {
        link.classList.remove('is-active');
        link.removeAttribute('aria-current');
      });
    };

    let frame = 0;
    const onScroll = () => {
      const scrolled = window.scrollY > 8;
      header?.classList.toggle('is-scrolled', scrolled);
      if (!scrolled) clearNav();
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(updateScrub);
    };

    let spy: IntersectionObserver | null = null;
    if ('IntersectionObserver' in window) {
      spy = new IntersectionObserver(
        (entries) => {
          const visible = entries
            .filter((entry) => entry.isIntersecting)
            .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
          if (!visible || window.scrollY <= 8) return;
          const id = (visible.target as HTMLElement).id;
          navLinks.forEach((link) => {
            const on = link.getAttribute('href') === `#${id}`;
            link.classList.toggle('is-active', on);
            if (on) link.setAttribute('aria-current', 'true');
            else link.removeAttribute('aria-current');
          });
        },
        { rootMargin: '-45% 0px -45% 0px', threshold: [0, 0.2, 0.45, 0.7] },
      );
      sections.forEach((section) => spy?.observe(section));
    }

    updateScrub();
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    reduce.addEventListener('change', onScroll);

    return () => {
      cancelAnimationFrame(frame);
      revealObserver?.disconnect();
      spy?.disconnect();
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      reduce.removeEventListener('change', onScroll);
    };
  }, [rootRef]);
}
