import React from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import Shell from './cv/Shell';
import Board from './cv/Board';
import ButlerPage from './cv/ButlerPage';
import NewTopicPage from './cv/NewTopic';
import ProjectPage from './cv/ProjectPage';
import ProjectsPage from './cv/ProjectsPage';
import SettingsPage from './cv/Settings';
import SearchPage from './cv/Search';
import TopicPage from './cv/TopicPage';
import UsagePage from './cv/UsagePage';
import NotFound from './pages/NotFound/NotFound';

const RoutesComponent = () => {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Board />} />
        <Route path="new" element={<NewTopicPage />} />
        <Route path="butler" element={<ButlerPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:key/*" element={<ProjectPage />} />
        <Route path="topics" element={<Navigate to="/" replace />} />
        <Route path="topics/:key" element={<TopicPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/:tab" element={<SettingsPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="usage" element={<UsagePage />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
};

export default RoutesComponent;
