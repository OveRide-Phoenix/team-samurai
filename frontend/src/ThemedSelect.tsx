import { useEffect, useRef, useState } from 'react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Check, ChevronDown } from 'lucide-react';

type Props = {
  readonly label: string; readonly name?: string; readonly value?: string;
  readonly defaultValue?: string; readonly disabled?: boolean;
  readonly options: readonly { readonly value: string; readonly label: string }[];
  readonly onChange?: (value: string) => void;
};
export function ThemedSelect({ label, name, value, defaultValue, disabled, options, onChange }: Props) {
  const initial = defaultValue ?? options[0]?.value ?? '';
  const [local, setLocal] = useState(initial);
  const button = useRef<HTMLButtonElement>(null);
  const selected = value ?? local;
  useEffect(() => {
    const form = button.current?.closest('form');
    const reset = () => setLocal(initial);
    form?.addEventListener('reset', reset);
    return () => form?.removeEventListener('reset', reset);
  }, [initial]);
  return <><input type="hidden" name={name} value={selected} disabled={disabled} /><DropdownMenu.Root>
    <DropdownMenu.Trigger asChild><button ref={button} type="button" className="themed-select" disabled={disabled} aria-label={label}><span>{options.find(option => option.value === selected)?.label ?? label}</span><ChevronDown size={15} /></button></DropdownMenu.Trigger>
    <DropdownMenu.Portal><DropdownMenu.Content className="workspace-menu themed-select-menu" align="start" sideOffset={6} collisionPadding={14}><DropdownMenu.RadioGroup value={selected} onValueChange={next => { setLocal(next); onChange?.(next); }}>{options.map(option => <DropdownMenu.RadioItem key={option.value} value={option.value} className="workspace-menu-item themed-select-option"><span>{option.label}</span><DropdownMenu.ItemIndicator><Check size={14} /></DropdownMenu.ItemIndicator></DropdownMenu.RadioItem>)}</DropdownMenu.RadioGroup></DropdownMenu.Content></DropdownMenu.Portal>
  </DropdownMenu.Root></>;
}
