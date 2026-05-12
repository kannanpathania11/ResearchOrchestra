"use client";

import React, { useState, useEffect, useRef } from "react";
import { 
  Send, 
  User as UserIcon, 
  Bot, 
  Loader2, 
  ChevronRight, 
  BookOpen,
  History,
  Settings,
  Sparkles,
  LogOut
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
  status?: string;
  isStreaming?: boolean;
};

export default function Dashboard() {
  const { user } = useAuth();
  const router = useRouter();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [currentStatus, setCurrentStatus] = useState("");
  const [report, setReport] = useState("");
  const [threadId, setThreadId] = useState<string | null>(null);
  
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, currentStatus]);

  const handleSignOut = async () => {
    await signOut(auth);
    router.push("/");
  };

  const getSuggestions = () => {
    return [
      "Prep me for a Google Software Internship",
      "Analysis of the Data Science market in 2026",
      "Deep dive study guide for Quantum Mechanics"
    ];
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isTyping) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsTyping(true);
    setReport("");
    setCurrentStatus("Initializing ResearchOrchestra...");

    try {
      let currentThreadId = threadId;
      if (!currentThreadId) {
        currentThreadId = Date.now().toString(); // simple pseudo-UUID
        setThreadId(currentThreadId);
      }

      const promptContext = input;

      const response = await fetch("http://localhost:8000/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          message: promptContext, 
          thread_id: currentThreadId 
        }),
      });

      if (!response.body) throw new Error("No response body");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantMessage = "";
      let isFirstToken = true;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const dataStr = line.slice(6);
            if (dataStr === "[DONE]") break;

            try {
              const data = JSON.parse(dataStr);
              if (data.type === "status") {
                setCurrentStatus(data.content);
              } else if (data.type === "token") {
                assistantMessage += data.content;
                setReport((prev) => prev + data.content);
                
                if (isFirstToken) {
                  setMessages((prev) => [
                    ...prev,
                    { id: "assistant-report", role: "assistant", content: "Generating comprehensive report...", isStreaming: true }
                  ]);
                  isFirstToken = false;
                }
              } else if (data.type === "final") {
                 if (!assistantMessage) {
                    setMessages((prev) => [
                        ...prev,
                        { id: Date.now().toString(), role: "assistant", content: data.content }
                    ]);
                 }
              } else if (data.type === "error") {
                 setMessages((prev) => [
                     ...prev,
                     { id: Date.now().toString(), role: "assistant", content: `⚠️ Error: ${data.content}` }
                 ]);
              }
            } catch (e) {
              console.error("Error parsing SSE chunk", e);
            }
          }
        }
      }
    } catch (err) {
      console.error(err);
      setMessages((prev) => [
        ...prev,
        { id: Date.now().toString(), role: "assistant", content: "Sorry, I encountered an error. Please ensure the backend is running." },
      ]);
    } finally {
      setIsTyping(false);
      setCurrentStatus("");
    }
  };

  return (
    <div className="flex h-screen bg-[#0a0a0a] text-white overflow-hidden font-sans">
      {/* Sidebar */}
      <aside className="w-64 border-r border-white/5 flex flex-col glass p-4">
        <div className="flex items-center gap-3 mb-8 px-2">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center cursor-pointer" onClick={() => router.push('/')}>
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <h1 className="font-bold text-lg tracking-tight cursor-pointer" onClick={() => router.push('/')}>ResearchOrchestra</h1>
        </div>

        <nav className="flex-1 space-y-1">
          <SidebarItem icon={<History size={18} />} label="Chat History" active={true} />
        </nav>

        <div className="pt-4 border-t border-white/5 space-y-1">
          <SidebarItem icon={<Settings size={18} />} label="Settings" />
          <div className="mt-4 bg-white/5 border border-white/10 rounded-xl p-3">
             <div className="flex items-center gap-3 mb-3">
               <div className="w-8 h-8 bg-gradient-to-tr from-purple-500 to-pink-500 rounded-full flex items-center justify-center shadow-lg">
                 <UserIcon size={16} className="text-white" />
               </div>
                <div className="flex flex-col overflow-hidden">
                  <span className="text-sm font-medium truncate">{user?.email || "Student User"}</span>
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

      {/* Main Content */}
      <main className="flex-1 flex overflow-hidden relative">
        {/* Chat Area */}
        <div className={cn(
            "flex flex-col transition-all duration-500 ease-in-out",
            report ? "w-1/3 border-r border-white/5" : "w-full items-center"
        )}>
          <div 
            ref={scrollRef}
            className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6 w-full max-w-2xl"
          >
            {messages.length === 0 && (
                <div className="h-full flex flex-col items-center justify-center text-center space-y-4">
                    <div className="w-16 h-16 bg-white/5 rounded-2xl flex items-center justify-center mb-4">
                        <Sparkles className="w-8 h-8 text-blue-500" />
                    </div>
                    <h2 className="text-2xl font-bold">What are we researching today?</h2>
                    <p className="text-white/40 max-w-sm">
                        Select a suggestion below or type your own request to begin.
                    </p>
                    <div className="grid grid-cols-1 gap-2 w-full mt-8">
                        {getSuggestions().map((suggestion, idx) => (
                           <SuggestionCard 
                               key={idx}
                               text={suggestion} 
                               onClick={() => setInput(suggestion)}
                           />
                        ))}
                    </div>
                </div>
            )}

            {messages.map((m) => (
              <div
                key={m.id}
                className={cn(
                  "flex gap-4 group",
                  m.role === "user" ? "flex-row-reverse" : "flex-row"
                )}
              >
                <div className={cn(
                  "w-8 h-8 rounded-lg flex items-center justify-center shrink-0",
                  m.role === "user" ? "bg-white/10" : "bg-blue-600/20 text-blue-400"
                )}>
                  {m.role === "user" ? <UserIcon size={16} /> : <Bot size={16} />}
                </div>
                <div className={cn(
                  "max-w-[85%] rounded-2xl p-4 text-sm leading-relaxed",
                  m.role === "user" ? "bg-white/5 border border-white/5" : "bg-blue-600/5 border border-blue-600/10"
                )}>
                  {m.content}
                </div>
              </div>
            ))}

            {currentStatus && (
              <div className="flex items-center gap-3 text-blue-400 animate-pulse px-12">
                <Loader2 size={14} className="animate-spin" />
                <span className="text-xs font-medium tracking-wide uppercase italic">{currentStatus}</span>
              </div>
            )}
          </div>

          {/* Input Area */}
          <div className="p-6 w-full max-w-2xl">
            <form 
              onSubmit={handleSubmit}
              className="relative flex items-center"
            >
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Type your request here..."
                className="w-full bg-white/5 border border-white/10 rounded-2xl py-4 pl-6 pr-14 focus:outline-none focus:border-blue-500/50 transition-all text-sm"
              />
              <button
                type="submit"
                disabled={isTyping}
                className="absolute right-3 w-10 h-10 bg-blue-600 hover:bg-blue-500 rounded-xl flex items-center justify-center transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-blue-600/20"
              >
                {isTyping ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
              </button>
            </form>
            <p className="text-[10px] text-white/20 text-center mt-3">
              ResearchOrchestra utilizes multi-agent orchestration. Reports may take 1-2 minutes to synthesize.
            </p>
          </div>
        </div>

        {/* Report Area */}
        <AnimatePresence>
          {report && (
            <motion.div
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              className="flex-1 bg-[#0d0d0d] flex flex-col"
            >
              <div className="h-16 border-b border-white/5 flex items-center justify-between px-8 bg-[#0a0a0a]/50 backdrop-blur-xl">
                <div className="flex items-center gap-2">
                    <BookOpen size={16} className="text-blue-500" />
                    <span className="text-sm font-semibold">Intelligence Report</span>
                </div>
                <div className="flex items-center gap-4">
                     <span className="text-[10px] bg-blue-500/10 text-blue-400 px-2 py-1 rounded uppercase font-bold tracking-tighter">Drafting...</span>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto custom-scrollbar p-12">
                <div className="max-w-3xl mx-auto prose prose-invert prose-blue prose-sm">
                  <ReactMarkdown>{report}</ReactMarkdown>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}

function SidebarItem({ icon, label, active = false, onClick }: { icon: React.ReactNode, label: string, active?: boolean, onClick?: () => void }) {
  return (
    <div 
      onClick={onClick}
      className={cn(
        "flex items-center gap-3 px-3 py-2 rounded-xl cursor-pointer transition-all group",
        active ? "bg-blue-600/10 text-blue-400" : "hover:bg-white/5 text-white/60 hover:text-white"
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

function SuggestionCard({ text, onClick }: { text: string, onClick: () => void }) {
    return (
        <div 
            onClick={onClick}
            className="flex items-center justify-between px-4 py-3 bg-white/5 border border-white/5 rounded-xl cursor-pointer hover:bg-white/10 hover:border-white/10 transition-all group"
        >
            <span className="text-xs text-white/60 group-hover:text-white/90">{text}</span>
            <ChevronRight size={14} className="text-white/20 group-hover:text-blue-500 transition-colors" />
        </div>
    )
}
