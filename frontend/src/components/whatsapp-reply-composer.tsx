import { useRef, useState, type FormEvent } from 'react';
import { Send, Smile, X } from 'lucide-react';

export function WhatsAppReplyComposer({ reply, setReply, sending, onSubmit }: {
  reply: string; setReply: (text: string) => void; sending: boolean; onSubmit: (event: FormEvent) => void;
}) {
  const [emojiOpen, setEmojiOpen] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  return <form className="wa-composer" onSubmit={onSubmit}>
    {emojiOpen ? <div className="wa-emoji-picker" role="group" aria-label="Choose an emoji">{['😀', '😊', '👍', '🙏', '❤️', '🎉', '✅', '👋'].map(emoji => <button type="button" key={emoji} aria-label={`Insert ${emoji}`} onClick={() => {
      const start = input.current?.selectionStart ?? reply.length;
      const end = input.current?.selectionEnd ?? reply.length;
      setReply(reply.slice(0, start) + emoji + reply.slice(end));
      setEmojiOpen(false);
      input.current?.focus();
    }}>{emoji}</button>)}</div> : null}
    <button type="button" className="wa-composer-icon" aria-label={emojiOpen ? 'Close emoji picker' : 'Insert emoji'} aria-expanded={emojiOpen} disabled={sending} onClick={() => setEmojiOpen(!emojiOpen)}>{emojiOpen ? <X /> : <Smile />}</button>
    <textarea ref={input} aria-label="WhatsApp message" value={reply} onChange={event => setReply(event.target.value)} placeholder="Type a message" rows={1} disabled={sending} onKeyDown={event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
        event.preventDefault();
        if (reply.trim() && !sending) event.currentTarget.form?.requestSubmit();
      }
    }} />
    <button className="wa-send" type="submit" aria-label={sending ? 'Sending message' : 'Send message'} title="Send (Enter). Shift+Enter for a new line." disabled={!reply.trim() || sending}><Send aria-hidden="true" /></button>
  </form>;
}
