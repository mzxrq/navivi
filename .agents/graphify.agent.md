# Graphify — Code Analysis & Visualization

Graphify is a comprehensive code analysis tool that parses, visualizes, and searches code using tree-sitter AST parsing and graph analysis.

## Commands

Use graphify for:
- **Code analysis**: Parse code into AST, extract structure, dependencies
- **Graph visualization**: Visualize code relationships, call graphs, dependency graphs
- **Code search**: Find patterns, functions, classes, imports across codebase
- **Custom workflows**: Build custom analysis pipelines using networkx graphs

## Basic Usage

```python
import graphifyy as gfy
from graphifyy import CodeGraph, Analyzer

# 1. Create a code graph from a directory or file
graph = CodeGraph(language="python")
graph.add_file("src/file.py")
# or add entire directory:
graph.add_directory("src/", recursive=True)

# 2. Analyze code structure
analyzer = Analyzer(graph)
functions = analyzer.extract_functions()
classes = analyzer.extract_classes()
imports = analyzer.extract_imports()

# 3. Query and search
calls = analyzer.find_function_calls("my_function")
usages = analyzer.find_all_usages("MyClass")
dependencies = analyzer.get_dependencies()

# 4. Visualize
graph.visualize(output="graph.html")
```

## Supported Languages

Graphify includes tree-sitter parsers for: Python, JavaScript/TypeScript, Go, Rust, C/C++, Java, Ruby, PHP, Bash, JSON, YAML, and 15+ more.

## Common Workflows

### Extract all functions from Python file
```python
graph = CodeGraph(language="python")
graph.add_file("app.py")
funcs = Analyzer(graph).extract_functions()
for func in funcs:
    print(f"{func.name} at line {func.start_line}")
```

### Find all imports across directory
```python
graph = CodeGraph(language="python")
graph.add_directory("src/")
imports = Analyzer(graph).extract_imports()
```

### Build dependency graph
```python
graph = CodeGraph(language="python")
graph.add_directory(".")
deps = Analyzer(graph).build_dependency_graph()
# Returns networkx graph with function/class dependencies
```

### Search for patterns
```python
analyzer = Analyzer(graph)
# Find all function calls to specific function
calls = analyzer.find_function_calls("render")
# Find all class instantiations
instances = analyzer.find_class_instantiations("VideoRenderer")
```

## Tips

- Use `language` parameter to specify the language (auto-detected from file extension by default)
- For large codebases, use `recursive=False` and add directories selectively
- Visualizations are saved as interactive HTML by default
- Use networkx graph directly for custom analysis: `graph.nx_graph`
- For pattern matching, use tree-sitter query syntax in `analyzer.query()`

## Integration with Navivi

Potential uses in this project:
- Analyze Python video pipeline for function dependencies
- Visualize React component hierarchy  
- Find all calls to specific rendering functions
- Extract all API endpoints and their handlers
- Track data flow through the GPS parser

---

For full docs, see: https://github.com/Graphify-Labs/graphify
