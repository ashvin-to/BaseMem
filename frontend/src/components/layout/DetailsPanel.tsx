import { Info, FileText, CheckCircle, AlertCircle, Lightbulb, Clock, Target, Code2, Box } from 'lucide-react';
import { useSelection } from '../../context/SelectionContext';
import { formatDateTime } from '../../lib/format';

export default function DetailsPanel() {
  const { selection } = useSelection();

  if (!selection) {
    return (
      <div className="flex flex-col h-full text-muted-foreground">
        <div className="p-6 border-b border-border">
          <h3 className="font-bold text-lg flex items-center gap-2 text-foreground">
            <Info className="w-5 h-5 text-amber-400" />
            Details
          </h3>
        </div>
        <div className="flex-1 flex items-center justify-center p-6 text-sm">
          Select a note, code symbol, or project to view details.
        </div>
      </div>
    );
  }

  const { type, data } = selection;

  const renderNoteDetails = () => {
    const getIcon = (kind?: string | null) => {
      switch (kind) {
        case 'decision': return <CheckCircle className="w-4 h-4 text-amber-400" />;
        case 'issue': return <AlertCircle className="w-4 h-4 text-red-400" />;
        case 'question': return <Lightbulb className="w-4 h-4 text-amber-400" />;
        default: return <FileText className="w-4 h-4 text-amber-400" />;
      }
    };

    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3 border-b border-border pb-4">
          <div className="p-2 bg-accent/30 border border-border">
            {getIcon(data.kind)}
          </div>
          <span className="font-semibold text-foreground capitalize">{data.kind}</span>
        </div>

        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-2">Title</h4>
          <p className="font-medium text-foreground text-sm">{data.title || 'Untitled Note'}</p>
        </div>

        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-2">Content</h4>
          <div className="text-sm bg-accent/20 p-4 border border-border whitespace-pre-wrap text-foreground leading-relaxed">
            {data.content}
          </div>
        </div>

        {data.created_at && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground pt-4 border-t border-border">
            <Clock className="w-3 h-3" />
            {formatDateTime(data.created_at)}
          </div>
        )}
      </div>
    );
  };

  const renderPlanetDetails = () => (
    <div className="space-y-6">
      <div className="flex items-center gap-3 border-b border-border pb-4">
        <div className="p-2 bg-accent/30 border border-border">
          <Target className="w-4 h-4 text-amber-400" />
        </div>
        <span className="font-semibold text-foreground">{data.display_topic || data.topic || data.title || data.id}</span>
      </div>

      {data.goal && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-2">Goal</h4>
          <p className="text-sm text-foreground">{data.goal}</p>
        </div>
      )}

      {data.current_state && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-2">Current State</h4>
          <p className="text-sm text-muted-foreground">{data.current_state}</p>
        </div>
      )}

      {data.status && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">Status:</span>
          <span className="px-2 py-0.5 bg-accent/30 text-foreground capitalize">{data.status}</span>
        </div>
      )}
    </div>
  );

  const renderCodeDetails = () => (
    <div className="space-y-6">
      <div className="flex items-center gap-3 border-b border-border pb-4">
        <div className="p-2 bg-accent/30 border border-border">
          {data.kind === 'file' ? <Code2 className="w-4 h-4 text-amber-400" /> : <Box className="w-4 h-4 text-amber-400" />}
        </div>
        <span className="font-semibold text-foreground">{data.title || 'Code Symbol'}</span>
      </div>

      <div>
        <h4 className="text-xs font-semibold text-muted-foreground mb-2">{data.kind === 'file' ? 'File Path' : 'Details'}</h4>
        <div className="text-sm bg-accent/20 p-4 border border-border whitespace-pre-wrap text-foreground font-mono">
          {data.content}
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex flex-col h-full text-muted-foreground">
      <div className="p-6 border-b border-border flex items-center justify-between">
        <h3 className="font-bold text-lg flex items-center gap-2 capitalize text-foreground">
          <Info className="w-5 h-5 text-amber-400" />
          {type} Details
        </h3>
      </div>

      <div className="p-6 flex-1 overflow-y-auto space-y-6">
        {type === 'note' && renderNoteDetails()}
        {type === 'planet' && renderPlanetDetails()}
        {type === 'code' && renderCodeDetails()}
      </div>
    </div>
  );
}
