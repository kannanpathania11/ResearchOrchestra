"use client";

import React, { useState, useEffect, useRef } from "react";
import { 
  Send, 
  User as UserIcon, 
  Bot, 
  Loader2, 
  ChevronRight, 
  Settings,
  Sparkles,
  LogOut,
  Plus,
  MessageSquare,
  Trash2
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { useAuth } from "@/context/AuthContext";
import { auth } from "@/lib/firebase";
import { signOut } from "firebase/auth";
import { useRouter } from "next/navigation";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
};

type HistoryItem = {
  thread_id: string;
  title: string;
};

// Stable streaming message ID — always the same so we can find & update it
const STREAMING_MSG_ID = "assistant-streaming";

export default function Dashboard() {
  const { user } = useAuth();
  const router = useRouter();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [currentStatus, setCurrentStatus] = useState("");
  const [threadId, setThreadId] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, currentStatus]);

  // ─── History ────────────────────────────────────────────────────────────────

  const fetchHistory = async () => {
    if (!user?.uid) return;
    try {
      const res = await fetch(
        `http://localhost:8000/chat/history?user_id=${encodeURIComponent(user.uid)}`
      );
      const data = await res.json();
      setHistory(data.threads || []);
    } catch (e) {
      console.error("Failed to fetch history", e);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, [user?.uid]);

  const startNewChat = () => {
    setThreadId(null);
    setMessages([]);
    setInput("");
    setCurrentStatus("");
  };

  const loadThread = async (id: string) => {
    if (id === threadId) return;
    try {
      setIsHistoryLoading(true);
      const res = await fetch(
        `http://localhost:8000/chat/history/${id}?user_id=${encodeURIComponent(user?.uid || "")}`
      );
      const data = await res.json();
      const loaded: Message[] = data.messages.map((m: any, idx: number) => ({
        id: `loaded-${idx}`,
        role: m.role,
        content: m.content,
      }));
      setMessages(loaded);
      setThreadId(id);
      setInput("");
      setCurrentStatus("");
    } catch (e) {
      console.error("Failed to load thread", e);
    } finally {
      setIsHistoryLoading(false);
    }
  };

  const deleteThread = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation(); // Don't trigger loadThread
    try {
      setDeletingId(id);
      await fetch(
        `http://localhost:8000/chat/history/${id}?user_id=${encodeURIComponent(user?.uid || "")}`,
        { method: "DELETE" }
      );
      // If we deleted the active thread, reset to new chat
      if (threadId === id) startNewChat();
      await fetchHistory();
    } catch (e) {
      console.error("Failed to delete thread", e);
    } finally {
      setDeletingId(null);
    }
  };

  // ─── Auth ────────────────────────────────────────────────────────────────────

  const handleSignOut = async () => {
    await signOut(auth);
    router.push("/");
  };

  // ─── Chat Submit ─────────────────────────────────────────────────────────────

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isTyping) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input,
    };

    setMessages((prev) => [...prev, userMessage]);
    const sentInput = input;
    setInput("");
    setIsTyping(true);
    setCurrentStatus("Initializing ResearchOrchestra...");

    try {
      let currentThreadId = threadId;
      if (!currentThreadId) {
        currentThreadId = Date.now().toString();
        setThreadId(currentThreadId);
      }

      const response = await fetch("http://localhost:8000/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: sentInput,
          thread_id: currentThreadId,
          user_id: user?.uid || "anonymous",
        }),
      });

      if (!response.body) throw new Error("No response body");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let streamingStarted = false;
      let doneReading = false;

      while (!doneReading) {
        const { value, done } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;

          const dataStr = line.slice(6).trim();

          // ── Stream finished ──────────────────────────────────────────────
          if (dataStr === "[DONE]") {
            // Finalize the streaming message (remove isStreaming flag)
            setMessages((prev) =>
              prev.map((m) =>
                m.id === STREAMING_MSG_ID
                  ? { ...m, id: Date.now().toString(), isStreaming: false }
                  : m
              )
            );
            setCurrentStatus("");
            doneReading = true;
            break;
          }

          try {
            const data = JSON.parse(dataStr);

            // ── Status update ──────────────────────────────────────────────
            if (data.type === "status") {
              setCurrentStatus(data.content);

            // ── Streaming token → appended directly into chat bubble ───────
            } else if (data.type === "token") {
              setCurrentStatus(""); // Clear status once tokens start arriving

              if (!streamingStarted) {
                // First token: create the assistant message in chat
                setMessages((prev) => [
                  ...prev,
                  {
                    id: STREAMING_MSG_ID,
                    role: "assistant",
                    content: data.content,
                    isStreaming: true,
                  },
                ]);
                streamingStarted = true;
              } else {
                // Subsequent tokens: append to existing streaming message
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === STREAMING_MSG_ID
                      ? { ...m, content: m.content + data.content }
                      : m
                  )
                );
              }

            // ── Final (non-streaming) response ─────────────────────────────
            } else if (data.type === "final") {
              if (!streamingStarted) {
                setMessages((prev) => [
                  ...prev,
                  {
                    id: Date.now().toString(),
                    role: "assistant",
                    content: data.content,
                  },
                ]);
              }

            // ── Error ──────────────────────────────────────────────────────
            } else if (data.type === "error") {
              setMessages((prev) => [
                ...prev,
                {
                  id: Date.now().toString(),
                  role: "assistant",
                  content: `⚠️ ${data.content}`,
                },
              ]);
            }
          } catch {
            // Non-JSON line, skip
          }
        }
      }
    } catch (err) {
      console.error(err);
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          role: "assistant",
          content: "Sorry, I encountered an error. Please ensure the backend is running.",
        },
      ]);
    } finally {
      setIsTyping(false);
      setCurrentStatus("");
      fetchHistory();
    }
  };

  // ─── Suggestions ─────────────────────────────────────────────────────────────

  const suggestions = [
    "Prep me for a Google Software Internship",
    "Analysis of the Data Science market in 2026",
    "Deep dive study guide for Quantum Mechanics",
  ];

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-screen bg-[#0a0a0a] text-white overflow-hidden font-sans">

      {/* ── Sidebar ── */}
      <aside className="w-64 border-r border-white/5 flex flex-col glass p-4">

        {/* Logo */}
        <div className="flex items-center gap-3 mb-5 px-2">
          <div
            className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center cursor-pointer"
            onClick={() => router.push("/")}
          >
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <h1
            className="font-bold text-lg tracking-tight cursor-pointer"
            onClick={() => router.push("/")}
          >
            ResearchOrchestra
          </h1>
        </div>

        {/* New Chat Button */}
        <button
          id="new-chat-btn"
          onClick={startNewChat}
          className="flex items-center justify-center gap-2 w-full bg-blue-600 hover:bg-blue-500 text-white py-2.5 rounded-xl transition-all font-medium text-sm shadow-lg shadow-blue-600/20 mb-5"
        >
          <Plus size={16} /> New Chat
        </button>

        {/* History List */}
        <div className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-2 px-3">
          Recent Chats
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto custom-scrollbar pr-1">
          {history.length === 0 ? (
            <div className="text-xs text-white/30 px-3 py-2 italic">No previous chats yet.</div>
          ) : (
            history.map((h) => (
              <HistoryItem
                key={h.thread_id}
                item={h}
                active={threadId === h.thread_id}
                isDeleting={deletingId === h.thread_id}
                onClick={() => loadThread(h.thread_id)}
                onDelete={(e) => deleteThread(e, h.thread_id)}
              />
            ))
          )}
        </nav>

        {/* User Footer */}
        <div className="pt-4 border-t border-white/5 space-y-1">
          <SidebarItem icon={<Settings size={18} />} label="Settings" />
          <div className="mt-4 bg-white/5 border border-white/10 rounded-xl p-3">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-8 h-8 bg-gradient-to-tr from-purple-500 to-pink-500 rounded-full flex items-center justify-center shadow-lg">
                <UserIcon size={16} className="text-white" />
              </div>
              <div className="flex flex-col overflow-hidden">
                <span className="text-sm font-medium truncate">
                  {user?.email || "Student User"}
                </span>
              </div>
            </div>
            <button
              onClick={handleSignOut}
              className="w-full flex items-center justify-center gap-2 text-xs text-white/60 hover:text-white bg-white/5 hover:bg-white/10 py-2 rounded-lg transition-colors"
            >
              <LogOut size={14} /> Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* ── Main Chat Area ── */}
      <main className="flex-1 flex flex-col overflow-hidden">

        {/* Message List */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto custom-scrollbar px-4 py-8"
        >
          <div className="max-w-3xl mx-auto space-y-8">
          {/* Empty state */}
          {messages.length === 0 && !isHistoryLoading && (
            <div className="h-full flex flex-col items-center justify-center text-center space-y-4 max-w-xl mx-auto">
              <div className="w-16 h-16 bg-white/5 rounded-2xl flex items-center justify-center mb-4">
                <Sparkles className="w-8 h-8 text-blue-500" />
              </div>
              <h2 className="text-2xl font-bold">What are we researching today?</h2>
              <p className="text-white/40 max-w-sm">
                Select a suggestion below or type your own request to begin.
              </p>
              <div className="grid grid-cols-1 gap-2 w-full mt-8">
                {suggestions.map((s, idx) => (
                  <SuggestionCard key={idx} text={s} onClick={() => setInput(s)} />
                ))}
              </div>
            </div>
          )}

          {/* Loading history spinner */}
          {isHistoryLoading && (
            <div className="flex items-center justify-center h-40 text-white/30">
              <Loader2 size={28} className="animate-spin" />
            </div>
          )}

          </div>

          {/* Messages */}
          <div className="max-w-3xl mx-auto space-y-8">
          <AnimatePresence initial={false}>
            {messages.map((m) => (
              <motion.div
                key={m.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, ease: "easeOut" }}
                className={cn(
                  m.role === "user"
                    ? "flex justify-end"
                    : "flex flex-col w-full max-w-3xl"
                )}
              >
                {m.role === "user" ? (
                  /* ── User bubble ── */
                  <div className="max-w-[75%] bg-white/8 border border-white/10 rounded-2xl px-5 py-3 text-sm leading-relaxed text-white/90 shadow-sm">
                    {m.content}
                  </div>
                ) : (
                  /* ── AI message (ChatGPT-style, no bubble) ── */
                  <div className="w-full">
                    {/* Model label row */}
                    <div className="flex items-center gap-2 mb-3">
                      <div className="w-6 h-6 rounded-md bg-blue-600/30 flex items-center justify-center shrink-0">
                        <Bot size={13} className="text-blue-400" />
                      </div>
                      <span className="text-[11px] font-semibold text-white/30 uppercase tracking-widest">
                        ResearchOrchestra
                      </span>
                    </div>

                    {/* Content */}
                    <div className="ai-message-content pl-1 text-[15px] leading-7 text-white/88">
                      <ReactMarkdown
                        components={{
                          h1: ({ children }) => (
                            <h1 className="text-2xl font-bold text-white mt-6 mb-3 pb-2 border-b border-white/10">{children}</h1>
                          ),
                          h2: ({ children }) => (
                            <h2 className="text-xl font-bold text-white mt-5 mb-2">{children}</h2>
                          ),
                          h3: ({ children }) => (
                            <h3 className="text-base font-semibold text-white/90 mt-4 mb-1.5">{children}</h3>
                          ),
                          p: ({ children }) => (
                            <p className="text-white/80 my-2 leading-7">{children}</p>
                          ),
                          strong: ({ children }) => (
                            <strong className="font-semibold text-white">{children}</strong>
                          ),
                          em: ({ children }) => (
                            <em className="italic text-white/70">{children}</em>
                          ),
                          ul: ({ children }) => (
                            <ul className="my-2 ml-4 space-y-1 list-none">{children}</ul>
                          ),
                          ol: ({ children }) => (
                            <ol className="my-2 ml-4 space-y-1 list-decimal list-inside">{children}</ol>
                          ),
                          li: ({ children }) => (
                            <li className="flex gap-2 text-white/80 items-start">
                              <span className="mt-2.5 w-1.5 h-1.5 rounded-full bg-blue-400/70 shrink-0" />
                              <span>{children}</span>
                            </li>
                          ),
                          code: ({ inline, children }: any) =>
                            inline ? (
                              <code className="bg-white/8 text-blue-300 text-[13px] rounded px-1.5 py-0.5 font-mono">{children}</code>
                            ) : (
                              <pre className="bg-[#111] border border-white/10 rounded-xl p-4 my-3 overflow-x-auto">
                                <code className="text-[13px] text-green-300 font-mono">{children}</code>
                              </pre>
                            ),
                          blockquote: ({ children }) => (
                            <blockquote className="border-l-2 border-blue-500/60 pl-4 my-3 text-white/60 italic">{children}</blockquote>
                          ),
                          hr: () => <hr className="my-4 border-white/10" />,
                          a: ({ href, children }) => (
                            <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 underline underline-offset-2 transition-colors">{children}</a>
                          ),
                        }}
                      >
                        {m.content}
                      </ReactMarkdown>

                      {/* Blinking cursor while streaming */}
                      {m.isStreaming && (
                        <span className="inline-block w-[2px] h-[1.1em] bg-blue-400 ml-0.5 animate-pulse align-middle rounded-full" />
                      )}
                    </div>
                  </div>
                )}
              </motion.div>
            ))}
          </AnimatePresence>
          </div>

          {/* Status indicator (agent thinking, before first token) */}
          {currentStatus && (
            <div className="max-w-3xl mx-auto flex items-center gap-3 mt-4">
              <div className="w-6 h-6 rounded-md bg-blue-600/30 flex items-center justify-center shrink-0">
                <Loader2 size={12} className="animate-spin text-blue-400" />
              </div>
              <span className="text-xs font-medium text-blue-400/80 tracking-wide uppercase italic animate-pulse">
                {currentStatus}
              </span>
            </div>
          )}
        </div>

        {/* Input Bar */}
        <div className="p-6 border-t border-white/5 bg-[#0a0a0a]/80 backdrop-blur-xl">
          <form
            onSubmit={handleSubmit}
            className="relative flex items-center max-w-3xl mx-auto"
          >
            <input
              id="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type your research request..."
              disabled={isTyping}
              className="w-full bg-white/5 border border-white/10 rounded-2xl py-4 pl-6 pr-14 focus:outline-none focus:border-blue-500/50 transition-all text-sm disabled:opacity-50"
            />
            <button
              id="chat-submit-btn"
              type="submit"
              disabled={isTyping || !input.trim()}
              className="absolute right-3 w-10 h-10 bg-blue-600 hover:bg-blue-500 rounded-xl flex items-center justify-center transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-blue-600/20"
            >
              {isTyping ? (
                <Loader2 size={18} className="animate-spin" />
              ) : (
                <Send size={18} />
              )}
            </button>
          </form>
          <p className="text-[10px] text-white/20 text-center mt-3">
            ResearchOrchestra uses multi-agent orchestration. Responses may take 1–2 minutes.
          </p>
        </div>
      </main>
    </div>
  );
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function HistoryItem({
  item,
  active,
  isDeleting,
  onClick,
  onDelete,
}: {
  item: HistoryItem;
  active: boolean;
  isDeleting: boolean;
  onClick: () => void;
  onDelete: (e: React.MouseEvent) => void;
}) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "group flex items-center gap-2 px-3 py-2 rounded-xl cursor-pointer transition-all",
        active
          ? "bg-blue-600/10 text-blue-400"
          : "hover:bg-white/5 text-white/60 hover:text-white"
      )}
    >
      <MessageSquare size={14} className={active ? "text-blue-400 shrink-0" : "text-white/30 shrink-0 group-hover:text-white/60"} />
      <span className="text-xs font-medium flex-1 truncate">{item.title}</span>

      {/* Delete button — appears on hover */}
      <button
        id={`delete-thread-${item.thread_id}`}
        onClick={onDelete}
        disabled={isDeleting}
        className={cn(
          "p-1 rounded-lg transition-all opacity-0 group-hover:opacity-100",
          "hover:bg-red-500/20 hover:text-red-400 text-white/30",
          isDeleting && "opacity-100 cursor-wait"
        )}
        title="Delete conversation"
      >
        {isDeleting ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          <Trash2 size={12} />
        )}
      </button>
    </div>
  );
}

function SidebarItem({
  icon,
  label,
  active = false,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "flex items-center gap-3 px-3 py-2 rounded-xl cursor-pointer transition-all group",
        active
          ? "bg-blue-600/10 text-blue-400"
          : "hover:bg-white/5 text-white/60 hover:text-white"
      )}
    >
      <div className={active ? "text-blue-400" : "text-white/40 group-hover:text-white/80"}>
        {icon}
      </div>
      <span className="text-sm font-medium">{label}</span>
      {active && <div className="ml-auto w-1 h-4 bg-blue-600 rounded-full" />}
    </div>
  );
}

function SuggestionCard({ text, onClick }: { text: string; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      className="flex items-center justify-between px-4 py-3 bg-white/5 border border-white/5 rounded-xl cursor-pointer hover:bg-white/10 hover:border-white/10 transition-all group"
    >
      <span className="text-xs text-white/60 group-hover:text-white/90">{text}</span>
      <ChevronRight size={14} className="text-white/20 group-hover:text-blue-500 transition-colors" />
    </div>
  );
}
