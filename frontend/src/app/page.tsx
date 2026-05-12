"use client";

import React from "react";
import { motion } from "framer-motion";
import { 
  ArrowRight, 
  MessageSquare, 
  Zap, 
  Layers, 
  Sparkles,
  ChevronRight
} from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";

export default function LandingPage() {
  const { user } = useAuth();

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white overflow-hidden relative font-sans">
      {/* Background Effects */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full h-[500px] opacity-30 pointer-events-none">
        <div className="absolute inset-0 bg-gradient-to-b from-blue-600/20 via-blue-900/5 to-transparent blur-3xl"></div>
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-purple-600/10 rounded-full blur-3xl"></div>
        <div className="absolute top-1/3 right-1/4 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl"></div>
      </div>

      {/* Navigation */}
      <nav className="relative z-10 flex items-center justify-between px-8 py-6 max-w-7xl mx-auto">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-tr from-blue-600 to-purple-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-500/20">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <span className="font-bold text-xl tracking-tight">ResearchOrchestra</span>
        </div>
        <div className="flex items-center gap-4">
          {user ? (
            <Link 
              href="/chat"
              className="px-6 py-2.5 rounded-full bg-white/10 hover:bg-white/20 transition-all font-medium border border-white/10 flex items-center gap-2"
            >
              Go to Dashboard <ArrowRight size={16} />
            </Link>
          ) : (
            <Link 
              href="/auth"
              className="px-6 py-2.5 rounded-full bg-blue-600 hover:bg-blue-500 transition-all font-medium shadow-lg shadow-blue-600/20 flex items-center gap-2"
            >
              Get Started <ArrowRight size={16} />
            </Link>
          )}
        </div>
      </nav>

      {/* Hero Section */}
      <main className="relative z-10 max-w-7xl mx-auto px-8 pt-20 pb-32">
        <div className="max-w-4xl mx-auto text-center space-y-8">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/5 border border-white/10 text-blue-400 text-sm font-medium mb-4"
          >
            <Sparkles size={14} />
            <span>AI-Powered Research Intelligence</span>
          </motion.div>
          
          <motion.h1 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="text-5xl md:text-7xl font-bold tracking-tight leading-tight"
          >
            One research pipeline <br/>
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-purple-400 to-blue-500">
              for all your goals.
            </span>
          </motion.h1>

          <motion.p 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="text-lg md:text-xl text-white/60 max-w-2xl mx-auto leading-relaxed"
          >
            A single autonomous engine for Job Scenario Analysis, Interview Intel, and Academic Help.
          </motion.p>

          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="flex items-center justify-center pt-8"
          >
             <Link 
              href={user ? "/chat" : "/auth"}
              className="px-8 py-4 rounded-full bg-white text-black hover:bg-white/90 transition-all font-semibold text-lg flex items-center gap-2 shadow-xl shadow-white/10"
            >
              Launch Research <ArrowRight size={20} />
            </Link>
          </motion.div>
        </div>

        {/* Feature Cards */}
        <div className="grid md:grid-cols-3 gap-6 mt-32">
          <FeatureCard 
            icon={<MessageSquare className="w-8 h-8 text-blue-400" />}
            title="Interactive Intelligence"
            description="Engage in fluid, real-time conversations with an agent that maintains deep context and session history."
            delay={0.4}
          />
          <FeatureCard 
            icon={<Zap className="w-8 h-8 text-purple-400" />}
            title="Rapid Synthesis"
            description="Lightning-fast information retrieval designed for quick fact-finding and immediate data persistence."
            delay={0.5}
          />
          <FeatureCard 
            icon={<Layers className="w-8 h-8 text-pink-400" />}
            title="Multi-Agent Pipeline"
            description="Our most advanced flow. An autonomous loop that clarifies, plans, reflects, and synthesizes comprehensive reports."
            delay={0.6}
          />
        </div>

        {/* Use Case Carousel */}
        <div className="mt-32">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold mb-4">One Pipeline, Three Solutions</h2>
            <p className="text-white/40">Explore how our unified research engine handles complex scenarios.</p>
          </div>
          <UseCasesCarousel />
        </div>
      </main>
    </div>
  );
}

function FeatureCard({ icon, title, description, delay }: { icon: React.ReactNode, title: string, description: string, delay: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay }}
      className="p-8 rounded-3xl bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20 transition-all group backdrop-blur-sm"
    >
      <div className="w-14 h-14 rounded-2xl bg-white/5 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
        {icon}
      </div>
      <h3 className="text-xl font-semibold mb-3">{title}</h3>
      <p className="text-white/60 leading-relaxed text-sm">
        {description}
      </p>
      <div className="mt-6 flex items-center gap-2 text-sm font-medium text-white/40 group-hover:text-white transition-colors cursor-pointer">
        Explore feature <ChevronRight size={14} />
      </div>
    </motion.div>
  );
}

const USE_CASES = [
  {
    title: "Job Scenario Analysis",
    mode: "JOB SCENARIO",
    description: "Deep-dive into job market dynamics, salary benchmarks, and skill demand. Stay ahead of 2026 trends with automated market synthesis.",
    example: "What is the job market for Data Scientists in 2026?",
    color: "from-blue-500/20 to-blue-600/5"
  },
  {
    title: "Interview Intel",
    mode: "INTERVIEW INTEL",
    description: "Uncover hiring processes and company culture. Generate role-specific preparation reports and targeted interview questions.",
    example: "Prep me for a Google SWE internship interview",
    color: "from-purple-500/20 to-purple-600/5"
  },
  {
    title: "Academic Help",
    mode: "ACADEMIC HELP",
    description: "Transform complex student topics into comprehensive study guides. Perfect for deep-dives into research topics and thesis preparation.",
    example: "Create a deep-dive study guide on Quantum Computing",
    color: "from-pink-500/20 to-pink-600/5"
  }
];

function UseCasesCarousel() {
  const [index, setIndex] = React.useState(0);

  React.useEffect(() => {
    const timer = setInterval(() => {
      setIndex((prev) => (prev + 1) % USE_CASES.length);
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="relative max-w-4xl mx-auto overflow-hidden rounded-3xl border border-white/10 bg-white/5 backdrop-blur-md">
      <div className="flex transition-transform duration-700 ease-in-out" style={{ transform: `translateX(-${index * 100}%)` }}>
        {USE_CASES.map((useCase, i) => (
          <div key={i} className="w-full shrink-0 p-12">
            <div className="flex flex-col md:flex-row gap-12 items-center">
              <div className="flex-1 space-y-6">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs font-bold tracking-widest text-blue-400 uppercase">
                  {useCase.mode}
                </div>
                <h3 className="text-4xl font-bold">{useCase.title}</h3>
                <p className="text-white/60 text-lg leading-relaxed">{useCase.description}</p>
                <div className="pt-4">
                  <p className="text-xs text-white/40 uppercase font-bold tracking-wider mb-2">Try asking:</p>
                  <div className="p-4 rounded-xl bg-white/5 border border-white/5 italic text-blue-300/80">
                    "{useCase.example}"
                  </div>
                </div>
              </div>
              <div className={`hidden md:block w-64 h-64 rounded-2xl bg-gradient-to-br ${useCase.color} border border-white/10 flex items-center justify-center relative overflow-hidden`}>
                 <Sparkles className="w-24 h-24 text-white/10 absolute -bottom-4 -right-4" />
                 <div className="w-20 h-20 bg-white/10 rounded-full blur-2xl absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2"></div>
              </div>
            </div>
          </div>
        ))}
      </div>
      
      <div className="absolute bottom-6 left-12 flex gap-2">
        {USE_CASES.map((_, i) => (
          <button 
            key={i}
            onClick={() => setIndex(i)}
            className={`w-2 h-2 rounded-full transition-all ${i === index ? "w-8 bg-blue-500" : "bg-white/20"}`}
          />
        ))}
      </div>
    </div>
  );
}
