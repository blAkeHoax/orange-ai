import React from 'react';
import HomeView from './HomeView';
import ChatView from './ChatView';
import SecondaryViews from './SecondaryViews';

export default function WorkspaceContainer({
  activeView,
  onToggleDrawer,
  isDrawerOpen,
  messages,
  onSendMessage,
  isExecuting,
  userName,
  onMemoryChanged,
  activeAdvisory,
  onDismissAdvisory,
  onSnoozeAdvisory,
  onExecuteAdvisory,
  onNewChat
}) {
  return (
    <main className="workspace-main-content">
      {activeView === 'home' && (
        <HomeView
          onToggleDrawer={onToggleDrawer}
          isDrawerOpen={isDrawerOpen}
          onSendMessage={onSendMessage}
          userName={userName}
          onMemoryChanged={onMemoryChanged}
        />
      )}

      {activeView === 'chat' && (
        <ChatView
          onToggleDrawer={onToggleDrawer}
          isDrawerOpen={isDrawerOpen}
          messages={messages}
          onSendMessage={onSendMessage}
          isExecuting={isExecuting}
          activeAdvisory={activeAdvisory}
          onDismissAdvisory={onDismissAdvisory}
          onSnoozeAdvisory={onSnoozeAdvisory}
          onExecuteAdvisory={onExecuteAdvisory}
          onNewChat={onNewChat}
        />
      )}

      {['jobs', 'memory', 'activity', 'permissions', 'tools', 'settings'].includes(activeView) && (
        <SecondaryViews
          viewId={activeView}
          onToggleDrawer={onToggleDrawer}
          isDrawerOpen={isDrawerOpen}
          onRunInChat={onSendMessage}
          onMemoryChanged={onMemoryChanged}
        />
      )}
    </main>
  );
}
