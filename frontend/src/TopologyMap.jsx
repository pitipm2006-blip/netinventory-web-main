import React, { useEffect, useState } from 'react';
import ReactFlow, { Background, Controls, MiniMap } from 'reactflow';
import 'reactflow/dist/style.css';

const TopologyMap = () => {
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Consultamos el estado de los dispositivos para mapearlos como nodos
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    fetch(`${apiUrl}/api/v1/monitoring/status`, {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('netinventory_token')}`
      }
    })
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(data => {
        const generatedNodes = data.map((device, index) => {
          const x = (index % 3) * 250 + 100;
          const y = Math.floor(index / 3) * 150 + 100;

          return {
            id: String(device.id_dispositivo),
            data: { label: `${device.nombre_host}\n(${device.ip_gestion || 'Sin IP'})` },
            position: { x, y },
            style: { 
              background: '#1F2937', 
              color: '#F3F4F6', 
              border: `2px solid ${device.ultimo_sondeo?.estado === 'disponible' ? '#22C55E' : device.ultimo_sondeo ? '#EF4444' : '#6B7280'}`,
              borderRadius: '8px',
              padding: '10px',
              fontSize: '12px',
              textAlign: 'center'
            }
          };
        });

        const generatedEdges = [];
        if (generatedNodes.length > 1) {
          for (let i = 1; i < generatedNodes.length; i++) {
            generatedEdges.push({
              id: `e-${generatedNodes[0].id}-${generatedNodes[i].id}`,
              source: generatedNodes[0].id,
              target: generatedNodes[i].id,
              animated: true,
              style: { stroke: '#3B82F6' }
            });
          }
        }

        setNodes(generatedNodes);
        setEdges(generatedEdges);
        setLoading(false);
      })
      .catch(err => {
        console.error("Error al cargar la topología de red:", err);
        setLoading(false);
      });
  }, []);

  if (loading) return <div className="text-gray-400 p-6">Cargando topología lógica de red...</div>;

  return (
    <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 shadow-lg h-[600px] w-full">
      <div className="mb-3 flex justify-between items-center">
        <h3 className="text-lg font-semibold text-white">Topología lógica (vista provisional: sin enlaces reales)</h3>
        <span className="text-xs text-gray-400">Interactiva / Zoom y Desplazamiento activo</span>
      </div>
      
      <div className="h-[520px] w-full bg-gray-950 rounded-lg border border-gray-800">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
        >
          <Background color="#374151" gap={16} />
          <Controls />
          <MiniMap style={{ background: '#111827' }} nodeColor="#3B82F6" />
        </ReactFlow>
      </div>
    </div>
  );
};

export default TopologyMap;