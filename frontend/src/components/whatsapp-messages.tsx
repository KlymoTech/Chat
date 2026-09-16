import { Check, CheckCheck, CircleAlert, Clock3 } from 'lucide-react';
import { Fragment } from 'react';
import type { ChatMessage } from '@/types';

export function WhatsAppDeliveryStatus({ status }: { status: ChatMessage['deliveryStatus'] }) {
  if (!status || status === 'unknown') return null;
  const labels = { pending: 'Waiting to send', sent: 'Sent to WhatsApp', delivered: 'Delivered', read: 'Read', failed: 'Delivery failed' };
  const Icon = status === 'pending' ? Clock3 : status === 'failed' ? CircleAlert : status === 'sent' ? Check : CheckCheck;
  return <span className={`wa-delivery wa-delivery--${status}`} role="img" aria-label={labels[status]} title={labels[status]}><Icon aria-hidden="true" />{status === 'failed' ? <span>Not sent</span> : null}</span>;
}

function dayLabel(date: Date) {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return 'Today';
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' });
}

export function WhatsAppMessages({ messages, visitorName, agentName }: { messages: ChatMessage[]; visitorName: string; agentName: string }) {
  return <div className="wa-messages">{messages.map((message, index) => {
    const date = new Date(message.createdAt);
    const previous = messages[index - 1];
    const newDay = !previous || new Date(previous.createdAt).toDateString() !== date.toDateString();
    const outgoing = message.role === 'agent' || message.role === 'assistant';
    return <Fragment key={message.id}>
      {newDay ? <div className="wa-day"><span>{dayLabel(date)}</span></div> : null}
      {message.role === 'system' ? <div className="wa-system">{message.content}</div> : message.content ? <article className={`wa-message wa-message--${outgoing ? 'outgoing' : 'incoming'}`} aria-label={`${outgoing ? message.role === 'agent' ? 'You' : agentName : visitorName}: ${message.content}`}>
        <div className="wa-bubble">
          {outgoing ? <span className="wa-sender">{message.role === 'agent' ? 'You' : `${agentName} · AI`}</span> : null}
          <div className="wa-message-text" dir="auto">{message.content}</div>
          <div className="wa-message-meta"><time dateTime={message.createdAt} title={date.toLocaleString()}>{date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</time>{outgoing ? <WhatsAppDeliveryStatus status={message.deliveryStatus} /> : null}</div>
        </div>
        {message.citations?.map((citation) => <span className="wa-citation" key={citation.title}>{citation.title}</span>)}
      </article> : null}
    </Fragment>;
  })}</div>;
}
