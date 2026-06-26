import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { X, Plus } from 'lucide-react'
import { fetchTags, createTag, addTagToTrade, removeTagFromTrade } from '../lib/api'

export default function TagEditor({ tradeId, currentTags = [] }) {
  const queryClient = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)
  const [newTagName, setNewTagName] = useState('')

  const { data: allTags = [] } = useQuery({ queryKey: ['tags'], queryFn: fetchTags })

  const addMutation = useMutation({
    mutationFn: (tagId) => addTagToTrade(tradeId, tagId),
    onSuccess: () => queryClient.invalidateQueries(['trade', tradeId]),
  })
  const removeMutation = useMutation({
    mutationFn: (tagId) => removeTagFromTrade(tradeId, tagId),
    onSuccess: () => queryClient.invalidateQueries(['trade', tradeId]),
  })
  const createMutation = useMutation({
    mutationFn: (data) => createTag(data),
    onSuccess: (newTag) => {
      queryClient.invalidateQueries(['tags'])
      addMutation.mutate(newTag.id)
      setNewTagName('')
      setShowAdd(false)
    },
  })

  const currentTagIds = new Set(currentTags.map((t) => t.id))
  const availableTags = allTags.filter((t) => !currentTagIds.has(t.id))

  return (
    <div>
      <label className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">Tags</label>
      <div className="flex flex-wrap gap-1.5 mt-2">
        {currentTags.map((tag) => (
          <span
            key={tag.id}
            className="badge bg-[#2a2c30] text-[#8d91a6] gap-1"
            style={{ borderLeft: `3px solid ${tag.color}` }}
          >
            {tag.name}
            <button onClick={() => removeMutation.mutate(tag.id)} className="hover:text-[#de576f] transition-colors ml-0.5">
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="badge bg-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6] hover:bg-[#2a2d3a] transition-all gap-1"
        >
          <Plus className="w-3 h-3" /> Add
        </button>
      </div>
      {showAdd && (
        <div className="mt-2 p-3 bg-[#161718] rounded-lg border border-[#2a2c30] space-y-2">
          {availableTags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {availableTags.map((tag) => (
                <button
                  key={tag.id}
                  onClick={() => { addMutation.mutate(tag.id); setShowAdd(false) }}
                  className="badge bg-[#2a2c30] text-[#8d91a6] hover:bg-[#2a2d3a] transition-all cursor-pointer"
                  style={{ borderLeft: `3px solid ${tag.color}` }}
                >
                  {tag.name}
                </button>
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <input
              type="text" value={newTagName}
              onChange={(e) => setNewTagName(e.target.value)}
              placeholder="New tag name..."
              className="input flex-1"
              onKeyDown={(e) => { if (e.key === 'Enter' && newTagName.trim()) createMutation.mutate({ name: newTagName.trim() }) }}
            />
            <button
              onClick={() => { if (newTagName.trim()) createMutation.mutate({ name: newTagName.trim() }) }}
              disabled={!newTagName.trim()}
              className="btn-primary text-xs px-3"
            >Create</button>
          </div>
        </div>
      )}
    </div>
  )
}
