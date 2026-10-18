import { createContext, useContext } from 'react';
import { ComposerPrimitive } from '@assistant-ui/react';
import { createLibrary, defineComponent } from '@openuidev/react-lang';
import { z } from 'zod';
import { ArrowUp, Plus, Square, X } from 'lucide-react';
import { LiquidBackdrop } from './LiquidBackdrop';
import { OpenUIRender } from './OpenUIRender';

type ComposerControls = { workLabel?: string; onClearWork?: () => void; running: boolean; recovering: boolean; stopLabel: string; onExplore: () => void; onInput: (value: string) => void };
const ComposerContext = createContext<ComposerControls | null>(null);
const MessageText = defineComponent({
  name: 'MessageText', description: 'Literal founder or Proofseed message; never executable markup', props: z.object({ text: z.string() }),
  component: ({ props }) => <p className="chat-message-copy">{props.text}</p>,
});
const ReplyComposer = defineComponent({
  name: 'ReplyComposer', description: 'Company-scoped reply with send, stop and panel controls',
  props: z.object({ label: z.string(), placeholder: z.string() }),
  component: ({ props }) => {
    const controls = useContext(ComposerContext);
    if (!controls) return null;
    return <><div className="composer-work-scope" hidden={!controls.workLabel || controls.running}>{controls.workLabel && <><span>Run this step · {controls.workLabel}</span><button type="button" className="icon-button" onClick={controls.onClearWork} aria-label="Clear work approval"><X size={13} /></button></>}</div><ComposerPrimitive.Root className="composer"><LiquidBackdrop /><button type="button" className="composer-plus icon-button" onClick={controls.onExplore} aria-label="Explore idea panels"><Plus size={20} /></button><ComposerPrimitive.Input className="composer-input" rows={1} placeholder={props.placeholder} aria-label={props.label} onChange={event => controls.onInput(event.currentTarget.value)} maxLength={4000} />{!controls.running ? <ComposerPrimitive.Send asChild><button className="send-button" aria-label={controls.workLabel ? `Run ${controls.workLabel.toLowerCase()}` : 'Send message'}><ArrowUp size={19} /></button></ComposerPrimitive.Send> : <ComposerPrimitive.Cancel asChild><button className="send-button stop-button" disabled={controls.recovering} aria-label={controls.stopLabel}><Square size={14} fill="currentColor" /></button></ComposerPrimitive.Cancel>}</ComposerPrimitive.Root></>;
  },
});
export const chatLibrary = createLibrary({ components: [MessageText, ReplyComposer] });
export const messageResponse = (text: string) => `root = MessageText(${JSON.stringify(text)})`;
export function OpenUIMessageText({ text }: { text: string }) {
  return <OpenUIRender response={messageResponse(text)} library={chatLibrary} />;
}
export function OpenUIComposer({ label, placeholder, ...controls }: ComposerControls & { label: string; placeholder: string }) {
  return <ComposerContext.Provider value={controls}><OpenUIRender response={`root = ReplyComposer(${JSON.stringify(label)}, ${JSON.stringify(placeholder)})`} library={chatLibrary} /></ComposerContext.Provider>;
}
