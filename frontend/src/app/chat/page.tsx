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
  Trash2,
  FlaskConical,
  FileDown,
  Copy,
  Check,
  Square,
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
  isReport?: boolean;   // true when generated via Research Mode pipeline
};

type HistoryItem = {
  thread_id: string;
  title: string;
};

// Stable streaming message ID — always the same so we can find & update it
const STREAMING_MSG_ID = "assistant-streaming";
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
  const [researchMode, setResearchMode] = useState(false);
  const [researchPipelineMode, setResearchPipelineMode] = useState<"interview_intel" | "job_scenario" | "academic_help">("academic_help");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

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
        `${API_BASE_URL}/chat/history?user_id=${encodeURIComponent(user.uid)}`
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
    setResearchMode(false);
  };

  const loadThread = async (id: string) => {
    if (id === threadId) return;
    try {
      setIsHistoryLoading(true);
      const res = await fetch(
        `${API_BASE_URL}/chat/history/${id}?user_id=${encodeURIComponent(user?.uid || "")}`
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
        `${API_BASE_URL}/chat/history/${id}?user_id=${encodeURIComponent(user?.uid || "")}`,
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
    const isReportRequest = researchMode; // capture at submit time
    setInput("");
    setIsTyping(true);
    setCurrentStatus("Initializing ResearchOrchestra...");

    try {
      abortControllerRef.current = new AbortController();

      let currentThreadId = threadId;
      if (!currentThreadId) {
        currentThreadId = Date.now().toString();
        setThreadId(currentThreadId);
      }

      const response = await fetch(`${API_BASE_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: abortControllerRef.current.signal,
        body: JSON.stringify({
          message: sentInput,
          thread_id: currentThreadId,
          user_id: user?.uid || "anonymous",
          research_pipeline_mode: researchMode,
          research_mode: researchPipelineMode,
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
            // A real report always streams tokens (streamingStarted=true).
            // Clarification questions arrive as a single `final` event with no
            // preceding tokens, so streamingStarted stays false — exclude them.
            const finalId = Date.now().toString();
            setMessages((prev) =>
              prev.map((m) =>
                m.id === STREAMING_MSG_ID
                  ? { ...m, id: finalId, isStreaming: false, isReport: isReportRequest && streamingStarted }
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
              // `final` fires when no streaming happened — always a clarification
              // question or a non-streaming fallback, never a completed report.
              if (!streamingStarted) {
                setMessages((prev) => [
                  ...prev,
                  {
                    id: Date.now().toString(),
                    role: "assistant",
                    content: data.content,
                    isReport: false,
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
    } catch (err: any) {
      if (err.name === "AbortError") {
        const finalId = Date.now().toString();
        setMessages((prev) =>
          prev.map((m) =>
            m.id === STREAMING_MSG_ID
              ? { ...m, id: finalId, isStreaming: false, isReport: false }
              : m
          )
        );
      } else {
        console.error(err);
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now().toString(),
            role: "assistant",
            content: "Sorry, I encountered an error. Please ensure the backend is running.",
          },
        ]);
      }
    } finally {
      setIsTyping(false);
      setCurrentStatus("");
      fetchHistory();
    }
  };

  // ─── Report Actions ──────────────────────────────────────────────────────────

  const downloadReport = async (messageId: string, topic: string) => {
    const el = document.getElementById(`report-content-${messageId}`);
    if (!el) return;

    const date = new Date().toLocaleDateString("en-GB", {
      day: "numeric", month: "long", year: "numeric",
    });

    const dateSlug = new Date().toISOString().slice(0, 10);
    const topicSlug = topic.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);

    // Strip Tailwind classes from the HTML so we don't rely on the external stylesheet
    const cleanHtml = el.innerHTML.replace(/class="[^"]*"/g, "");

    const wrapper = document.createElement("div");
    wrapper.style.cssText = "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Georgia,sans-serif;max-width:820px;margin:40px auto;padding:0 32px;color:#1a1a1a;line-height:1.75;background:#fff;font-size:15px;";
    wrapper.innerHTML = `
      <style>
        h1 { font-size: 24px; font-weight: bold; margin-top: 24px; margin-bottom: 12px; border-bottom: 1px solid #e5e7eb; padding-bottom: 8px; color: #111827; }
        h2 { font-size: 20px; font-weight: bold; margin-top: 24px; margin-bottom: 12px; color: #111827; }
        h3 { font-size: 16px; font-weight: bold; margin-top: 16px; margin-bottom: 8px; color: #374151; }
        p { margin: 12px 0; color: #374151; }
        strong { font-weight: 600; color: #111827; }
        em { font-style: italic; }
        ul { margin: 12px 0 12px 24px; list-style-type: disc; }
        ol { margin: 12px 0 12px 24px; list-style-type: decimal; }
        li { margin-bottom: 6px; color: #374151; display: list-item; padding-left: 4px; }
        pre { background: #f3f4f6; padding: 16px; border-radius: 8px; overflow-x: auto; font-family: monospace; font-size: 13px; margin: 16px 0; border: 1px solid #e5e7eb; }
        code { font-family: monospace; font-size: 13px; color: #059669; }
        p > code, li > code { background: #f3f4f6; padding: 2px 6px; border-radius: 4px; color: #2563eb; }
        blockquote { border-left: 4px solid #3b82f6; padding-left: 16px; color: #4b5563; font-style: italic; margin: 16px 0; background: #eff6ff; padding: 12px 16px; border-radius: 0 8px 8px 0; }
        hr { margin: 24px 0; border: none; border-top: 1px solid #e5e7eb; }
        a { color: #3b82f6; text-decoration: underline; }
      </style>
      <div style="border-bottom:2px solid #e5e7eb;padding-bottom:16px;margin-bottom:32px;">
        <div style="font-size:13px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:#6b7280;">ResearchOrchestra</div>
        <div style="font-size:12px;color:#9ca3af;margin-top:4px;">Generated on ${date}</div>
      </div>
      ${cleanHtml}
      <div style="margin-top:48px;padding-top:16px;border-top:1px solid #e5e7eb;font-size:12px;color:#9ca3af;">ResearchOrchestra · AI-powered multi-agent research</div>
    `;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const html2pdf = (await import("html2pdf.js")).default as any;
    html2pdf()
      .set({
        margin: [12, 12, 12, 12],
        filename: `${topicSlug}-${dateSlug}.pdf`,
        image: { type: "jpeg", quality: 0.98 },
        html2canvas: { 
          scale: 2, 
          useCORS: true,
          // Prevent html2canvas from parsing Tailwind's v4 stylesheet which contains oklab colors
          ignoreElements: (node: any) => node.nodeName === 'STYLE' || node.nodeName === 'LINK'
        },
        jsPDF: { unit: "mm", format: "a4", orientation: "portrait" },
      })
      .from(wrapper)
      .save();
  };

  const copyMarkdown = async (content: string, messageId: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedId(messageId);
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      // clipboard API not available (rare)
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
              <div className="w-8 h-8 bg-linear-to-tr from-purple-500 to-pink-500 rounded-full flex items-center justify-center shadow-lg">
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
            {messages.map((m, idx) => (
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
                    <div
                      id={`report-content-${m.id}`}
                      className="ai-message-content pl-1 text-[15px] leading-7 text-white/88"
                    >
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
                            <ul className="my-2 ml-6 space-y-1 list-disc marker:text-blue-400">{children}</ul>
                          ),
                          ol: ({ children }) => (
                            <ol className="my-2 ml-6 space-y-1 list-decimal marker:text-blue-400">{children}</ol>
                          ),
                          li: ({ children }) => (
                            <li className="text-white/80 pl-1">{children}</li>
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
                        <span className="inline-block w-0.5 h-[1.1em] bg-blue-400 ml-0.5 animate-pulse align-middle rounded-full" />
                      )}
                    </div>

                    {/* Report action toolbar — only for completed research mode reports */}
                    {m.isReport && !m.isStreaming && (
                      <div className="flex items-center gap-2 mt-4 pt-4 border-t border-white/5">
                        <span className="text-[11px] text-purple-400/60 uppercase tracking-widest font-semibold mr-1">
                          Research Report
                        </span>
                        <button
                          onClick={() => {
                            const topic = messages.slice(0, idx).reverse().find(msg => msg.role === "user")?.content ?? "research-report";
                            downloadReport(m.id, topic);
                          }}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-purple-600/15 border border-purple-500/25 text-purple-300 hover:bg-purple-600/25 transition-all"
                        >
                          <FileDown size={13} />
                          Download PDF
                        </button>
                        <button
                          onClick={() => copyMarkdown(m.content, m.id)}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/5 border border-white/10 text-white/50 hover:text-white/80 hover:bg-white/8 transition-all"
                        >
                          {copiedId === m.id ? (
                            <><Check size={13} className="text-green-400" /><span className="text-green-400">Copied!</span></>
                          ) : (
                            <><Copy size={13} />Copy Markdown</>
                          )}
                        </button>
                      </div>
                    )}
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
              placeholder={researchMode ? "Describe your research topic for a deep report..." : "Type your research request..."}
              disabled={isTyping}
              className={cn(
                "w-full bg-white/5 border rounded-2xl py-4 pl-6 pr-14 focus:outline-none transition-all text-sm disabled:opacity-50",
                researchMode
                  ? "border-purple-500/30 focus:border-purple-500/60"
                  : "border-white/10 focus:border-blue-500/50"
              )}
            />
            {isTyping ? (
              <button
                type="button"
                onClick={() => abortControllerRef.current?.abort()}
                className="absolute right-3 w-10 h-10 rounded-xl flex items-center justify-center transition-all bg-red-600 hover:bg-red-500 shadow-red-600/20 shadow-lg text-white"
                title="Stop generating"
              >
                <Square size={16} fill="currentColor" />
              </button>
            ) : (
              <button
                id="chat-submit-btn"
                type="submit"
                disabled={!input.trim()}
                className={cn(
                  "absolute right-3 w-10 h-10 rounded-xl flex items-center justify-center transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-lg",
                  researchMode
                    ? "bg-purple-600 hover:bg-purple-500 shadow-purple-600/20"
                    : "bg-blue-600 hover:bg-blue-500 shadow-blue-600/20"
                )}
              >
                <Send size={18} />
              </button>
            )}
          </form>

          {/* Bottom bar: Research Mode toggle + disclaimer */}
          <div className="max-w-3xl mx-auto mt-3 space-y-2">
            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={() => setResearchMode((m) => !m)}
                disabled={isTyping}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all border",
                  researchMode
                    ? "bg-purple-600/20 border-purple-500/40 text-purple-300 hover:bg-purple-600/30"
                    : "bg-white/5 border-white/10 text-white/40 hover:text-white/70 hover:bg-white/8"
                )}
              >
                <FlaskConical size={12} />
                Research Mode
                {researchMode && (
                  <span className="ml-1 w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" />
                )}
              </button>

              <p className="text-[10px] text-white/20">
                {researchMode
                  ? "Deep research pipeline · structured report"
                  : "Multi-agent · responses may take 1–2 min"}
              </p>
            </div>

            {/* Mode pills — only visible when Research Mode is ON */}
            {researchMode && (
              <div className="flex items-center gap-2">
                {(
                  [
                    { key: "academic_help",   label: "Academic"       },
                    { key: "interview_intel", label: "Interview Prep" },
                    { key: "job_scenario",    label: "Job Market"     },
                  ] as const
                ).map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    disabled={isTyping}
                    onClick={() => setResearchPipelineMode(key)}
                    className={cn(
                      "px-3 py-1 rounded-full text-xs font-medium border transition-all",
                      researchPipelineMode === key
                        ? "bg-purple-600/30 border-purple-500/50 text-purple-200"
                        : "bg-white/5 border-white/10 text-white/40 hover:text-white/70 hover:bg-white/8"
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>
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
