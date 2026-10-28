import { useEffect, useId, useRef, useState } from 'react';

export default function ActionMenu({ label = 'Другие действия', children }) {
  const id = useId();
  const menuRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({});
  useEffect(() => {
    if (!open) return undefined;
    const close = event => {
      if (!(event.target instanceof Node && menuRef.current?.contains(event.target))) menuRef.current?.hidePopover();
    };
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
    return () => {
      window.removeEventListener('resize', close);
      window.removeEventListener('scroll', close, true);
    };
  }, [open]);
  return <>
    <button className="menu-trigger" type="button" popoverTarget={id} aria-label={label} onClick={event => {
      const rect = event.currentTarget.getBoundingClientRect();
      const below = Math.max(0, window.innerHeight - rect.bottom - 18);
      const above = Math.max(0, rect.top - 18);
      const down = below >= 300 || below >= above;
      setPosition({ left: Math.max(12, Math.min(rect.right - 236, window.innerWidth - 248)),
        maxHeight: Math.min(400, down ? below : above),
        ...(down ? { top: rect.bottom + 6, bottom: 'auto' } : { bottom: window.innerHeight - rect.top + 6, top: 'auto' }) });
    }}>•••</button>
    <div ref={menuRef} id={id} popover="auto" className="action-menu" style={position} onToggle={event => setOpen(event.newState === 'open')} onClick={event => {
      if (event.target.closest('button')) event.currentTarget.hidePopover();
    }}>{children}</div>
  </>;
}
