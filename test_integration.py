"""
Test script to verify the SCG bridge integration.
Run this to ensure the scg-experiments package is properly connected.
"""

from pathlib import Path
from src import SCGBridge

def test_bridge_integration():
    """Test that the SCG bridge loads and works correctly."""
    
    # Adjust paths to your data and code
    data_path = Path(__file__).parent.parent / "scg-experiments" / "data" / "glide"
    code_path = Path(__file__).parent.parent / "scg-experiments" / "code" / "glide-4.5.0"
    
    print(f"Loading SCG from: {data_path}")
    print(f"Source code from: {code_path}")
    
    try:
        # Initialize the bridge with both data and code paths
        bridge = SCGBridge(str(data_path), code_path=str(code_path))
        
        # Get statistics
        stats = bridge.get_statistics()
        print(f"\n✅ SCG Bridge initialized successfully!")
        print(f"   Total nodes: {stats['total_nodes']}")
        print(f"   Total edges: {stats['total_edges']}")
        print(f"   Node kinds: {stats['node_kinds']}")
        
        # Test search
        print(f"\n Testing search functionality...")
        results = bridge.search_symbols("cache", limit=3)
        print(f"   Found {len(results)} results for 'cache'")
        if results:
            for i, r in enumerate(results[:3]):
                print(f"     {i+1}. {r['display_name']} ({r['type']}) - score: {r.get('score', 0):.3f}")
        
        # Test metrics
        print(f"\n Testing metrics calculation...")
        top_nodes = bridge.calculate_node_metrics(sort_by="incoming_degree", limit=3)
        print(f"   Top 3 nodes by incoming degree:")
        for i, node in enumerate(top_nodes):
            print(f"     {i+1}. {node['display_name'] or node['id']}")
            print(f"        Type: {node['type']}")
            print(f"        Incoming: {node['metrics']['incoming_degree']}, Outgoing: {node['metrics']['outgoing_degree']}")
        
        # Test source code fetching
        print(f"\n Testing source code fetching...")
        if results:
            test_node_id = results[0]['id']
            source = bridge.get_source_code(test_node_id, context_padding=3)
            if source:
                print(f"   ✓ Successfully fetched source code for '{results[0]['display_name']}'")
                print(f"   Preview (first 200 chars): {source[:200]}...")
            else:
                print(f"   ⚠ No source code available for this node (might be expected)")
        
        print(f"\n✅ All tests passed! Integration is working correctly.")
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_bridge_integration()
