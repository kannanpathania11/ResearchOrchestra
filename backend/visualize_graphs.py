import os
import sys
from dotenv import load_dotenv

load_dotenv()

try:
    from IPython.display import Image, display
    HAS_IPYTHON = True
except ImportError:
    HAS_IPYTHON = False

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

try:
    from agents.graph import supervisor_graph
    from agents.graph import research_graph as research_pipeline_graph
except ImportError as e:
    print(f"Error importing graphs: {e}")
    sys.exit(1)


def save_and_display_graph(graph, name):
    """Saves the graph as a PNG and optionally displays it in a notebook."""
    print(f"Generating visualisation for: {name}...")
    try:
        png_bytes = graph.get_graph(xray=True).draw_mermaid_png()
        filename = f"graph_{name.lower().replace(' ', '_')}.png"
        with open(filename, "wb") as f:
            f.write(png_bytes)
        print(f"Saved to {filename}")
        if HAS_IPYTHON:
            display(Image(png_bytes))
        else:
            print("IPython not found, skipping display. PNG file saved.")
    except Exception as e:
        print(f"Failed to visualise {name}: {e}")


if __name__ == "__main__":
    # 1. Orchestrator (supervisor) graph
    save_and_display_graph(supervisor_graph, "Orchestrator Graph")

    # 2. Unified research pipeline (single graph, all three modes)
    save_and_display_graph(research_pipeline_graph, "Research Pipeline")

    print("\nVisualisation complete. Check the .png files in the current directory.")
