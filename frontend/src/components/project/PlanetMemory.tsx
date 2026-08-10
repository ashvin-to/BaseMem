import { useState } from 'react';
import { Activity, CheckCircle, Clock, Lightbulb, AlertCircle, FileText, Loader2, Plus, X } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSelection } from '../../context/SelectionContext';
import { api } from '../../lib/api';
import { formatDate } from '../../lib/format';
import type { Planet, Note } from '../../lib/types';

export default function PlanetMemory({ projectId }: { projectId?: string }) {
  const { setSelection } = useSelection();
  const queryClient = useQueryClient();
  const [showAddNote, setShowAddNote] = useState(false);
  const [noteKind, setNoteKind] = useState('note');
  const [noteTitle, setNoteTitle] = useState('');
  const [noteContent, setNoteContent] = useState('');

  const { data: planet, isLoading } = useQuery({
    queryKey: ['planet', projectId],
    queryFn: () => api.planets.get(projectId || ''),
    enabled: !!projectId,
  });

  const addNoteMutation = useMutation({
    mutationFn: () =>
      api.notes.create({
        topic: projectId || '',
        kind: noteKind,
        title: noteTitle,
        content: noteContent,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['planet', projectId] });
      setShowAddNote(false);
      setNoteKind('note');
      setNoteTitle('');
      setNoteContent('');
    },
  });

  if (isLoading) {
    return <div className="flex h-full items-center justify-center text-muted-foreground"><Loader2 className="w-6 h-6 animate-spin mr-2" /> Loading memory...</div>;
  }

  if (!planet) {
    return <div className="flex h-full items-center justify-center text-muted-foreground">Select a valid project to view memory.</div>;
  }

  const getIcon = (kind: string) => {
    switch (kind) {
      case 'decision': return <CheckCircle className="w-4 h-4 text-amber-400" />;
      case 'issue': return <AlertCircle className="w-4 h-4 text-red-400" />;
      case 'question': return <Lightbulb className="w-4 h-4 text-amber-400" />;
      default: return <FileText className="w-4 h-4 text-amber-400" />;
    }
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto p-6 max-w-4xl mx-auto space-y-8">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold flex items-center gap-2 text-foreground">
            Project Memory: {(planet as Planet).display_topic || (planet as Planet).topic}
          </h1>
          <button
            onClick={() => setShowAddNote(!showAddNote)}
            className="flex items-center gap-2 px-3 py-1.5 border border-border bg-amber-600 hover:bg-amber-700 text-white text-sm font-medium transition-colors"
          >
            {showAddNote ? <X className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
            {showAddNote ? 'Cancel' : 'Add Note'}
          </button>
        </div>

        {showAddNote && (
          <div className="bg-card border border-border p-4 space-y-3">
            <div className="flex gap-2">
              {['note', 'decision', 'issue', 'question', 'fact'].map(kind => (
                <button
                  key={kind}
                  onClick={() => setNoteKind(kind)}
                  className={`px-3 py-1 text-xs font-medium capitalize border transition-colors ${
                    noteKind === kind
                      ? 'bg-amber-600 text-white border-amber-600'
                      : 'border-border text-muted-foreground hover:bg-accent/30'
                  }`}
                >
                  {kind}
                </button>
              ))}
            </div>
            <input
              type="text"
              placeholder="Note title (optional)"
              value={noteTitle}
              onChange={(e) => setNoteTitle(e.target.value)}
              className="w-full bg-background border border-border px-3 py-2 text-sm focus:outline-none text-foreground"
            />
            <textarea
              placeholder="Note content..."
              value={noteContent}
              onChange={(e) => setNoteContent(e.target.value)}
              rows={3}
              className="w-full bg-background border border-border px-3 py-2 text-sm focus:outline-none text-foreground resize-none"
            />
            <div className="flex justify-end">
              <button
                onClick={() => addNoteMutation.mutate()}
                disabled={!noteContent.trim() || addNoteMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 border border-border bg-amber-600 hover:bg-amber-700 text-white text-sm font-medium transition-colors disabled:opacity-50"
              >
                {addNoteMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                Save Note
              </button>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-4">
          <div className="bg-card border border-border p-4">
            <h3 className="text-sm font-medium text-muted-foreground mb-1 uppercase tracking-wider">Current Goal</h3>
            <p className="font-medium text-foreground">{(planet as Planet).goal || 'No goal set'}</p>
          </div>
          <div className="bg-card border border-border p-4">
            <h3 className="text-sm font-medium text-muted-foreground mb-1 uppercase tracking-wider">Current State</h3>
            <p className="text-muted-foreground">{(planet as Planet).current_state || 'No current state'}</p>
          </div>
        </div>

        {(((planet as Planet).next_steps || []).length > 0) && (
          <div className="bg-accent/30 border border-border p-4">
            <h3 className="text-sm font-medium text-muted-foreground mb-2 uppercase tracking-wider">Next Steps</h3>
            <ul className="list-disc list-inside space-y-1">
              {((planet as Planet).next_steps || []).map((step: string, i: number) => (
                <li key={i} className="text-sm text-foreground">{step}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2 text-foreground">
          <Activity className="w-5 h-5 text-amber-400" />
          Timeline & Notes
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {(planet as Planet).notes?.map((note: Note) => (
            <div 
              key={note.id} 
              onClick={() => setSelection({ type: 'note', id: `note-${note.id}`, data: note })}
              className="group bg-card border border-border p-4 hover:border-amber-500/50 transition-colors cursor-pointer"
            >
              <div className="flex items-center gap-2 mb-2">
                {getIcon(note.kind)}
                <span className="text-sm font-medium capitalize text-foreground">{note.kind}</span>
                <span className="text-xs text-muted-foreground ml-auto flex items-center gap-1">
                  <Clock className="w-3 h-3" /> {formatDate(note.created_at)}
                </span>
              </div>
              <h4 className="font-semibold mb-1 text-foreground">{note.title || (note.content.substring(0, 30) + '...')}</h4>
              <p className="text-sm text-muted-foreground line-clamp-2">{note.content}</p>
            </div>
          ))}
          {(!((planet as Planet).notes || []).length) && (
            <div className="col-span-full p-8 text-center text-muted-foreground border border-dashed border-border">
              No notes found for this planet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
