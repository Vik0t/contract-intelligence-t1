import { useCallback, useEffect, useId, useRef, useState } from 'react';

function ConfirmationDialog({ options, onResolve }) {
  const ref = useRef(null);
  const id = useId();
  useEffect(() => {
    const previous = document.activeElement;
    const dialog = ref.current;
    dialog.showModal();
    dialog.querySelector('[data-cancel]')?.focus();
    return () => { dialog.close(); if (previous?.isConnected) previous.focus(); };
  }, []);
  return <dialog ref={ref} className="confirmation-dialog" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} onCancel={event => { event.preventDefault(); onResolve(false); }}>
    <h2 id={`${id}-title`}>{options.title}</h2><p id={`${id}-description`}>{options.description}</p>
    <div className="confirmation-actions"><button data-cancel type="button" className="secondary-button" onClick={() => onResolve(false)}>{options.cancelLabel || 'Отмена'}</button><button type="button" className={options.danger ? 'danger-button' : 'primary-button'} onClick={() => onResolve(true)}>{options.confirmLabel || 'Продолжить'}</button></div>
  </dialog>;
}

export function useConfirmation() {
  const [options, setOptions] = useState(null);
  const resolver = useRef(null);
  const confirm = useCallback(next => new Promise(resolve => {
    resolver.current?.(false);
    resolver.current = resolve;
    setOptions(next);
  }), []);
  const finish = useCallback(value => {
    const resolve = resolver.current;
    resolver.current = null;
    setOptions(null);
    resolve?.(value);
  }, []);
  useEffect(() => () => resolver.current?.(false), []);
  const cancel = useCallback(() => finish(false), [finish]);
  return [confirm, options ? <ConfirmationDialog key="confirmation" options={options} onResolve={finish} /> : null, cancel];
}
