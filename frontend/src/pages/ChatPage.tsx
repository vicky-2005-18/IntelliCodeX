import React, { useState } from 'react';
import api from '../services/api';
import { MessageSquareCode, Send, Sparkles, FileText, CheckCircle2 } from 'lucide-react';

interface ChatProps {
  currentRepo: string;
}

interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  chunks?: Array<{ file: string; name: string; lines: string; score: number }>;
  confidence?: number;
}

const ChatPage: React.FC<ChatProps> = ({ currentRepo }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: '1',
      sender: 'assistant',
      text: `Hello! I am IntelliCodeX AI Assistant for repository '${currentRepo}'. Ask me about authentication flows, JWT verification, specific methods, architecture structure, or unused code!`,
    },
  ]);
  const [input, setInput] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMsg: ChatMessage = { id: Date.now().toString(), sender: 'user', text: input };
    setMessages((prev) => [...prev, userMsg]);
    const queryText = input;
    setInput('');
    setLoading(true);

    try {
      const res = await api.post('/chat/ask', {
        repo_id: currentRepo,
        question: queryText,
        top_k: 5,
      });

      const assistantMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        sender: 'assistant',
        text: res.data.answer,
        chunks: res.data.retrieved_chunks,
        confidence: res.data.confidence_score,
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        sender: 'assistant',
        text: `Error querying repository: ${err.response?.data?.detail || err.message}. Make sure '${currentRepo}' has been ingested first.`,
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col space-y-4">
      <div className="flex items-center justify-between pb-4 border-b border-gray-800">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <MessageSquareCode className="w-7 h-7 text-brand-400" /> Repository AI Assistant
          </h1>
          <p className="text-xs text-gray-400">
            Ground-truth retrieval using RAG vector similarity and graph citations.
          </p>
        </div>
        <span className="text-xs px-3 py-1 bg-brand-500/10 border border-brand-500/30 text-brand-400 rounded-full font-mono">
          Repo: {currentRepo}
        </span>
      </div>

      {/* Messages Window */}
      <div className="flex-1 overflow-y-auto space-y-4 p-4 glass-card">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`flex flex-col ${m.sender === 'user' ? 'items-end' : 'items-start'}`}
          >
            <div
              className={`max-w-3xl p-4 rounded-xl text-sm leading-relaxed ${
                m.sender === 'user'
                  ? 'bg-brand-600 text-white rounded-br-none shadow-md'
                  : 'bg-gray-800/90 text-gray-200 border border-gray-700/60 rounded-bl-none'
              }`}
            >
              {m.sender === 'assistant' && (
                <div className="flex items-center justify-between gap-2 mb-2 pb-2 border-b border-gray-700/50">
                  <span className="text-xs font-bold text-brand-400 flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5" /> IntelliCodeX AI
                  </span>
                  {m.confidence !== undefined && (
                    <span className="text-xs text-emerald-400 font-semibold flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" /> Confidence: {Math.round(m.confidence * 100)}%
                    </span>
                  )}
                </div>
              )}
              <div className="whitespace-pre-wrap">{m.text}</div>

              {/* Retrieved Chunks Citations */}
              {m.chunks && m.chunks.length > 0 && (
                <div className="mt-4 pt-3 border-t border-gray-700/60 space-y-2">
                  <p className="text-xs font-semibold text-gray-400 flex items-center gap-1">
                    <FileText className="w-3.5 h-3.5" /> Context Citations:
                  </p>
                  <div className="grid grid-cols-1 gap-1.5">
                    {m.chunks.map((c, idx) => (
                      <div
                        key={idx}
                        className="text-xs font-mono bg-gray-900/80 px-2.5 py-1.5 rounded border border-gray-700/50 flex justify-between items-center text-gray-300"
                      >
                        <span>{c.file} :: {c.name} (L{c.lines})</span>
                        <span className="text-brand-400 font-semibold">sim: {c.score.toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-xs text-brand-400 animate-pulse">
            <Sparkles className="w-4 h-4" /> IntelliCodeX is reasoning over codebase context...
          </div>
        )}
      </div>

      {/* Input Box */}
      <form onSubmit={handleSend} className="flex gap-3">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about authentication, functions, architecture..."
          className="flex-1 bg-gray-900 border border-gray-700 rounded-xl px-5 py-3.5 text-sm text-white focus:outline-none focus:border-brand-500 transition shadow-inner"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="px-6 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white font-semibold rounded-xl shadow-lg shadow-brand-500/20 transition flex items-center gap-2 text-sm"
        >
          <Send className="w-4 h-4" /> Send
        </button>
      </form>
    </div>
  );
};

export default ChatPage;
