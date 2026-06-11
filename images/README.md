# ASTRA Architecture Diagrams

This directory contains all architecture diagrams for the ASTRA Autonomous 5G RAN Self-Healing xApp.

## 📁 Directory Structure

```
images/
├── architecture.mmd          # Master architecture diagram (Mermaid)
├── architecture.excalidraw   # Hand-drawn style source (Excalidraw)
├── architecture.puml         # UML version (PlantUML)
└── diagrams/
    ├── data-flow.mmd         # Detection → Healing data flow
    ├── deployment.mmd        # Kubernetes + Helm deployment topology
    ├── sequence-healing.mmd  # Reactive healing sequence diagram
    ├── sequence-preemptive.mmd # Preemptive healing sequence diagram
    ├── ml-pipeline.mmd       # ML training → inference → continual learning
    └── topology-coord.mmd    # Topology & multi-cell coordination detail
```

## 🎨 How to Render

### Mermaid (.mmd files)
1. **Online**: Paste content into [https://mermaid.live](https://mermaid.live)
2. **VS Code**: Install "Mermaid Preview" extension
3. **GitHub**: Renders natively in `.md` files
4. **CLI**: `npm i -g @mermaid-js/mermaid-cli && mmdc -i diagram.mmd -o diagram.svg`

### Excalidraw (.excalidraw)
1. Open [https://excalidraw.com](https://excalidraw.com)
2. File → Load → Select `.excalidraw` file
3. Edit hand-drawn style, export PNG/SVG

### PlantUML (.puml)
1. **Online**: Paste into [https://www.plantuml.com/plantuml/uml/](https://www.plantuml.com/plantuml/uml/)
2. **VS Code**: Install "PlantUML" extension
3. **CLI**: `java -jar plantuml.jar diagram.puml`

## 📊 Diagram Descriptions

| Diagram | Purpose | Use In |
|---------|---------|--------|
| `architecture.mmd` | Complete system overview — all components, data flows, infrastructure | README.md, docs/ARCHITECTURE.md, presentation slides |
| `data-flow.mmd` | Core ML pipeline: KPI → Buffer → AE → XAI → Classifier → Twin → E2 | Technical deep-dive, docs/DATA_FLOW.md |
| `deployment.mmd` | K8s resources, Helm chart, networking, security, monitoring | docs/DEPLOYMENT.md, ops runbooks |
| `sequence-healing.mmd` | Reactive loop: 11.4s detect→classify→twin→heal with all actors | docs/DEEP_DIVE.md, presentation |
| `sequence-preemptive.mmd` | Parallel preemptive path: ForecastHead → 60s alert → preemptive heal | Innovation highlight, presentation |
| `ml-pipeline.mmd` | Offline training → online inference → EWC continual learning | ML methodology section, paper appendix |
| `topology-coord.mmd` | Neighbor graph, HTTP broadcast, dashboard rendering | Multi-cell innovation section |

## 🎯 Presentation Export Tips

```
# Export all to SVG for slides
for f in *.mmd diagrams/*.mmd; do
  mmdc -i "$f" -o "${f%.mmd}.svg" -b transparent -w 1920
done

# High-res PNG for print
mmdc -i architecture.mmd -o architecture.png -b transparent -w 3840 -s 2
```

## 🎨 Color Legend (Consistent Across All Diagrams)

| Color | Hex | Layer |
|-------|-----|-------|
| Blue | `#38bdf8` | KPI Ingestion |
| Purple | `#a78bfa` | ML Intelligence |
| Green | `#4ade80` | Digital Twin |
| Orange | `#fb923c` | Healing & E2 Control |
| Yellow | `#fbbf24` | Multi-Cell Coordination |
| Gray | `#6b7280` | State & Persistence |
| Cyan | `#06b6d4` | API & Dashboard |
| Dashed Gray | `#9ca3af` | Kubernetes Infrastructure |
| Red | `#ef4444` | External Systems |

## 🔗 Embedding in Markdown

```markdown
<!-- In README.md or docs/ARCHITECTURE.md -->
```mermaid
%% Paste content of architecture.mmd here
```
```

## 📝 Updating Diagrams

1. Edit source file (`.mmd`, `.excalidraw`, or `.puml`)
2. Re-export SVG/PNG for presentations
3. Commit both source and exported images
4. Update this README if adding new diagrams

---

**Generated for ASTRA Hackathon Presentation**  
*Autonomous 5G RAN Self-Healing xApp*